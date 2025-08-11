import os
import re
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import json
from collections import Counter
import threading
import queue

# Load environment variables
load_dotenv()


# Try to import PDF libraries
try:
    import PyPDF2

    pdf_support = True
except ImportError:
    try:
        import pdfplumber

        PyPDF2 = pdfplumber
        pdf_support = True
    except ImportError:
        pdf_support = False
        print("⚠️ PDF support not available. Install PyPDF2 or pdfplumber")

# Try to import DOCX library
try:
    import docx

    docx_support = True
except ImportError:
    docx_support = False
    print("⚠️ DOCX support not available. Install python-docx")

# Import Enhanced ATS scraper
# Import Enhanced ATS scraper with fallback
fast_ats_support = False
try:
    from enhanced_ats_scraper import get_jobs_sync, FastJobRecommendationService

    fast_ats_support = True
    print("✅ Fast ATS scraper initialized successfully")
except ImportError as e:
    print(f"⚠️ Fast ATS scraper not available: {e}")
    print("⚠️ Falling back to basic job search")


    # Create a simple fallback function
    def get_jobs_sync(job_field, resume_data, **kwargs):
        """Simple fallback job search"""
        # Return some mock jobs for now
        return [
            {
                'id': f'job_1_{job_field}',
                'title': f'Senior {job_field}',
                'company': 'TechCorp',
                'location': 'Remote',
                'url': 'https://example.com/job1',
                'match_score': 85,
                'experience_level': 'senior',
                'department': 'Engineering',
                'ats_type': 'lever',
                'matching_skills': resume_data.get('skills', [])[:3],
                'missing_skills': ['Kubernetes', 'Docker'],
                'recommendation': 'Strong technical match for this role'
            },
            {
                'id': f'job_2_{job_field}',
                'title': f'Junior {job_field}',
                'company': 'StartupXYZ',
                'location': 'San Francisco, CA',
                'url': 'https://example.com/job2',
                'match_score': 72,
                'experience_level': 'junior',
                'department': 'Product',
                'ats_type': 'greenhouse',
                'matching_skills': resume_data.get('skills', [])[:2],
                'missing_skills': ['React', 'Node.js'],
                'recommendation': 'Good entry-level opportunity'
            }
        ]

# Import Original ATS scraper as fallback
try:
    from ats_scraper import JobRecommendationService

    ats_support = True
    job_service = JobRecommendationService()
    print("✅ Original ATS scraper available as fallback")
except ImportError as e:
    ats_support = False
    job_service = None
    print(f"⚠️ Original ATS scraper not available: {e}")

# Initialize Flask app
app = Flask(__name__)

# CORS configuration - Allow all origins for development
CORS(app, supports_credentials=True)

# Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resume_parser.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Google OAuth Configuration
app.config['GOOGLE_CLIENT_ID'] = os.getenv('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.getenv('GOOGLE_CLIENT_SECRET')

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# OAuth setup
oauth = None
google = None
oauth_enabled = False

if app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET']:
    try:
        from authlib.integrations.flask_client import OAuth

        oauth = OAuth(app)
        google = oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'}
        )
        oauth_enabled = True
        print("✅ Google OAuth configured successfully")
    except ImportError:
        print("⚠️ Authlib not installed. Run: pip install authlib")
    except Exception as e:
        print(f"⚠️ OAuth configuration error: {e}")
else:
    print("⚠️ Google OAuth credentials not provided")


# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    avatar_url = db.Column(db.String(200))
    google_id = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    resumes = db.relationship('Resume', backref='user', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'avatar_url': self.avatar_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resume_count': len(self.resumes)
        }


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Resume(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    linkedin = db.Column(db.String(255))
    skills = db.Column(db.Text)  # JSON string
    experience = db.Column(db.Text)  # JSON string
    education = db.Column(db.Text)  # JSON string
    keywords = db.Column(db.Text)  # JSON string
    raw_text = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'linkedin': self.linkedin,
            'skills': json.loads(self.skills) if self.skills else [],
            'experience': json.loads(self.experience) if self.experience else [],
            'education': json.loads(self.education) if self.education else [],
            'keywords': json.loads(self.keywords) if self.keywords else [],
            'is_public': self.is_public
        }


# Job Field Recommender Class
class JobFieldRecommender:
    def __init__(self):
        self.job_fields = {
            'Software Engineer': {
                'skills': ['Python', 'Java', 'JavaScript', 'C++', 'C#', 'Go', 'Ruby', 'TypeScript',
                           'React', 'Angular', 'Vue.js', 'Node.js', 'Django', 'Flask', 'Spring',
                           'Git', 'Docker', 'Kubernetes', 'AWS', 'Azure', 'REST API', 'GraphQL'],
                'keywords': ['software', 'developer', 'programming', 'coding', 'full-stack', 'backend',
                             'frontend', 'api', 'microservices', 'agile', 'scrum'],
                'weight': 1.0
            },
            'Data Scientist': {
                'skills': ['Python', 'R', 'Machine Learning', 'Deep Learning', 'TensorFlow', 'PyTorch',
                           'Scikit-learn', 'Pandas', 'NumPy', 'Matplotlib', 'Statistics', 'SQL',
                           'Jupyter', 'MATLAB', 'SAS', 'SPSS', 'NLP', 'Computer Vision'],
                'keywords': ['data', 'analysis', 'machine learning', 'ai', 'artificial intelligence',
                             'predictive', 'modeling', 'statistics', 'research', 'algorithm'],
                'weight': 1.0
            },
            'Data Engineer': {
                'skills': ['Python', 'SQL', 'Apache Spark', 'Hadoop', 'Kafka', 'Airflow', 'ETL',
                           'AWS', 'Azure', 'GCP', 'MongoDB', 'PostgreSQL', 'Redis', 'Elasticsearch',
                           'Docker', 'Kubernetes', 'Scala', 'Java', 'Databricks', 'Snowflake'],
                'keywords': ['data', 'pipeline', 'etl', 'warehouse', 'big data', 'streaming',
                             'database', 'infrastructure', 'architect', 'integration'],
                'weight': 1.0
            },
            'DevOps Engineer': {
                'skills': ['Docker', 'Kubernetes', 'Jenkins', 'Git', 'CI/CD', 'Terraform', 'Ansible',
                           'AWS', 'Azure', 'Linux', 'Bash', 'Python', 'Monitoring', 'Prometheus',
                           'Grafana', 'ELK Stack', 'Nginx', 'Apache', 'Security'],
                'keywords': ['devops', 'automation', 'deployment', 'infrastructure', 'cloud',
                             'continuous', 'integration', 'monitoring', 'reliability', 'sre'],
                'weight': 1.0
            },
            'Cloud Architect': {
                'skills': ['AWS', 'Azure', 'GCP', 'Terraform', 'CloudFormation', 'Docker', 'Kubernetes',
                           'Serverless', 'Lambda', 'Microservices', 'API Gateway', 'Load Balancing',
                           'Security', 'Networking', 'Python', 'Java', 'Node.js'],
                'keywords': ['cloud', 'architect', 'solution', 'infrastructure', 'scalability',
                             'migration', 'serverless', 'saas', 'paas', 'iaas'],
                'weight': 1.0
            },
            'Full Stack Developer': {
                'skills': ['JavaScript', 'React', 'Angular', 'Vue.js', 'Node.js', 'HTML5', 'CSS3',
                           'Python', 'Django', 'Flask', 'Java', 'Spring', 'SQL', 'MongoDB',
                           'REST API', 'GraphQL', 'Git', 'Docker', 'AWS'],
                'keywords': ['full-stack', 'fullstack', 'frontend', 'backend', 'web', 'application',
                             'responsive', 'ui', 'ux', 'api'],
                'weight': 1.0
            },
            'Mobile Developer': {
                'skills': ['Swift', 'Kotlin', 'React Native', 'Flutter', 'iOS', 'Android', 'Java',
                           'Objective-C', 'Xcode', 'Android Studio', 'API', 'Firebase', 'SQLite'],
                'keywords': ['mobile', 'ios', 'android', 'app', 'application', 'native', 'cross-platform'],
                'weight': 1.0
            },
            'Machine Learning Engineer': {
                'skills': ['Python', 'TensorFlow', 'PyTorch', 'Scikit-learn', 'MLflow', 'Kubeflow',
                           'Deep Learning', 'Neural Networks', 'Computer Vision', 'NLP', 'CUDA',
                           'Docker', 'Kubernetes', 'AWS SageMaker', 'Model Deployment'],
                'keywords': ['machine learning', 'ml', 'ai', 'deep learning', 'neural', 'model',
                             'training', 'deployment', 'mlops', 'production'],
                'weight': 1.0
            },
            'Business Analyst': {
                'skills': ['SQL', 'Excel', 'Tableau', 'Power BI', 'Python', 'R', 'Jira', 'Confluence',
                           'Agile', 'Scrum', 'Requirements Analysis', 'Data Analysis', 'Visio'],
                'keywords': ['business', 'analyst', 'requirements', 'stakeholder', 'process',
                             'improvement', 'strategy', 'reporting', 'dashboard'],
                'weight': 1.0
            },
            'QA Engineer': {
                'skills': ['Selenium', 'Jest', 'Cypress', 'JUnit', 'TestNG', 'Postman', 'JMeter',
                           'Python', 'Java', 'JavaScript', 'Git', 'CI/CD', 'Automation Testing'],
                'keywords': ['qa', 'quality', 'testing', 'test', 'automation', 'bug', 'defect',
                             'validation', 'regression', 'performance'],
                'weight': 1.0
            }
        }

    def calculate_match_score(self, user_skills, user_keywords, job_field_data):
        score = 0
        max_score = 0
        user_skills_lower = [s.lower() for s in user_skills]
        user_keywords_lower = [k['word'].lower() for k in user_keywords]
        field_skills_lower = [s.lower() for s in job_field_data['skills']]

        for skill in field_skills_lower:
            max_score += 60 / len(field_skills_lower)
            if skill in user_skills_lower:
                score += 60 / len(field_skills_lower)

        field_keywords_lower = [k.lower() for k in job_field_data['keywords']]
        for keyword in field_keywords_lower:
            max_score += 40 / len(field_keywords_lower)
            if keyword in user_keywords_lower:
                score += 40 / len(field_keywords_lower)

        if max_score > 0:
            percentage = (score / max_score) * 100
        else:
            percentage = 0

        return min(round(percentage), 100)

    def get_job_recommendations(self, skills, keywords, experience_text=""):
        recommendations = []
        for field_name, field_data in self.job_fields.items():
            match_score = self.calculate_match_score(skills, keywords, field_data)
            if experience_text:
                experience_lower = experience_text.lower()
                if field_name.lower() in experience_lower:
                    match_score = min(match_score + 10, 100)

            recommendations.append({
                'field': field_name,
                'match_percentage': match_score,
                'job_search_url': self.get_job_search_url(field_name)
            })

        recommendations.sort(key=lambda x: x['match_percentage'], reverse=True)
        return recommendations

    def get_job_search_url(self, field_name):
        search_query = field_name.replace(' ', '+')
        return {
            'linkedin': f'https://www.linkedin.com/jobs/search/?keywords={search_query}',
            'indeed': f'https://www.indeed.com/jobs?q={search_query}',
            'glassdoor': f'https://www.glassdoor.com/Job/jobs.htm?sc.keyword={search_query}'
        }


# Resume Parser Class
class ResumeParser:
    def __init__(self):
        self.skills_database = {
            'programming_languages': [
                'Python', 'JavaScript', 'Java', 'C++', 'C#', 'PHP', 'Ruby', 'Go', 'Swift', 'Kotlin',
                'TypeScript', 'Scala', 'R', 'MATLAB', 'Perl', 'Rust', 'Dart', 'Objective-C', 'C',
                'VB.NET', 'F#', 'Haskell', 'Clojure', 'Erlang', 'Elixir', 'Lua', 'Shell', 'Bash'
            ],
            'web_technologies': [
                'React', 'Angular', 'Vue.js', 'Node.js', 'Express.js', 'Django', 'Flask', 'Spring',
                'ASP.NET', 'Laravel', 'Ruby on Rails', 'jQuery', 'Bootstrap', 'Tailwind CSS',
                'HTML5', 'CSS3', 'SASS', 'LESS', 'Webpack', 'Vite', 'Next.js', 'Nuxt.js',
                'Svelte', 'Ember.js', 'Backbone.js', 'Redux', 'MobX', 'GraphQL', 'REST API'
            ],
            'databases': [
                'MySQL', 'PostgreSQL', 'MongoDB', 'SQLite', 'Redis', 'Oracle', 'SQL Server',
                'Cassandra', 'DynamoDB', 'Firebase', 'Elasticsearch', 'Neo4j', 'CouchDB',
                'MariaDB', 'Amazon RDS', 'Google Cloud SQL', 'Azure SQL Database'
            ],
            'cloud_platforms': [
                'AWS', 'Azure', 'Google Cloud Platform', 'GCP', 'Digital Ocean', 'Heroku',
                'Vercel', 'Netlify', 'Firebase', 'Supabase', 'PlanetScale', 'Railway'
            ],
            'devops_tools': [
                'Docker', 'Kubernetes', 'Jenkins', 'Git', 'GitHub', 'GitLab', 'Bitbucket',
                'CI/CD', 'Terraform', 'Ansible', 'Chef', 'Puppet', 'Nginx', 'Apache',
                'Linux', 'Ubuntu', 'CentOS', 'RedHat', 'Vagrant', 'CircleCI', 'Travis CI'
            ],
            'data_science_ml': [
                'Machine Learning', 'Deep Learning', 'TensorFlow', 'PyTorch', 'Scikit-learn',
                'Pandas', 'NumPy', 'Matplotlib', 'Seaborn', 'Jupyter', 'Tableau', 'Power BI',
                'Apache Spark', 'Hadoop', 'Kafka', 'Airflow', 'MLflow', 'Kubeflow',
                'OpenCV', 'NLTK', 'spaCy', 'Hugging Face', 'Computer Vision', 'NLP'
            ],
            'soft_skills': [
                'Leadership', 'Team Management', 'Communication', 'Problem Solving',
                'Critical Thinking', 'Analytical Skills', 'Creativity', 'Adaptability',
                'Time Management', 'Strategic Planning', 'Negotiation', 'Presentation',
                'Training', 'Mentoring', 'Customer Service', 'Sales', 'Marketing'
            ]
        }

        self.job_keywords = [
            'experienced', 'certified', 'expert', 'specialist', 'manager', 'developer',
            'engineer', 'architect', 'analyst', 'consultant', 'lead', 'senior', 'junior',
            'professional', 'agile', 'scrum', 'project', 'team', 'client', 'business',
            'technical', 'solution', 'implementation', 'development', 'design', 'analysis'
        ]

        self.all_skills = []
        for category, skills in self.skills_database.items():
            self.all_skills.extend(skills)

    def extract_text_from_pdf(self, file_path):
        if not pdf_support:
            raise ValueError("PDF support not available. Install PyPDF2 or pdfplumber")
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            print(f"Error reading PDF: {e}")
            raise ValueError(f"Could not read PDF: {str(e)}")

    def extract_text_from_docx(self, file_path):
        if not docx_support:
            raise ValueError("DOCX support not available. Install python-docx")
        try:
            doc = docx.Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text
        except Exception as e:
            print(f"Error reading DOCX: {e}")
            raise ValueError(f"Could not read DOCX: {str(e)}")

    def extract_text_from_txt(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            print(f"Error reading TXT: {e}")
            raise ValueError(f"Could not read TXT: {str(e)}")

    def extract_contact_info(self, text):
        contact_info = {}
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        email_match = re.search(email_pattern, text)
        if email_match:
            contact_info['email'] = email_match.group()

        phone_patterns = [
            r'(\+?1?[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}',
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
        ]
        for pattern in phone_patterns:
            phone_match = re.search(pattern, text)
            if phone_match:
                contact_info['phone'] = phone_match.group()
                break

        linkedin_pattern = r'linkedin\.com/in/[\w-]+'
        linkedin_match = re.search(linkedin_pattern, text, re.IGNORECASE)
        if linkedin_match:
            contact_info['linkedin'] = linkedin_match.group()

        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines[:5]:
            if any(header in line.lower() for header in ['objective', 'summary', 'experience', 'education']):
                continue
            if '@' in line or re.search(r'\d{3}', line):
                continue
            if len(line.split()) <= 4 and len(line) < 50 and line[0].isupper():
                contact_info['name'] = line
                break

        return contact_info

    def extract_skills(self, text):
        found_skills = []
        text_lower = text.lower()
        for skill in self.all_skills:
            pattern = r'\b' + re.escape(skill.lower()) + r'\b'
            if re.search(pattern, text_lower):
                found_skills.append(skill)
        return list(set(found_skills))

    def extract_experience(self, text):
        experience = []
        lines = text.split('\n')
        exp_started = False
        current_exp = []

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            if re.search(r'\b(experience|employment|work history)\b', line, re.IGNORECASE):
                exp_started = True
                continue
            if exp_started and re.search(r'\b(education|skills|certifications)\b', line, re.IGNORECASE):
                break
            if exp_started:
                if re.search(r'\b(\d{4}|\w+\s*(Inc|LLC|Corp|Company|Ltd))\b', line):
                    if current_exp:
                        experience.append(' '.join(current_exp))
                        current_exp = []
                    current_exp.append(line)
                elif current_exp:
                    current_exp.append(line)

        if current_exp:
            experience.append(' '.join(current_exp))
        return experience[:5]

    def extract_education(self, text):
        education = []
        lines = text.split('\n')
        degree_patterns = [
            r'\b(Bachelor|Master|PhD|Ph\.D|MBA|Associate|Diploma)\b',
            r'\b(B\.S\.|B\.A\.|M\.S\.|M\.A\.|B\.E\.|B\.Tech|M\.Tech)\b'
        ]
        edu_keywords = ['university', 'college', 'institute', 'school', 'academy']
        edu_started = False

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if re.search(r'\beducation\b', line, re.IGNORECASE):
                edu_started = True
                continue
            if edu_started and re.search(r'\b(experience|skills|certifications|projects)\b', line, re.IGNORECASE):
                break
            if edu_started or any(re.search(pattern, line, re.IGNORECASE) for pattern in degree_patterns):
                if any(keyword in line.lower() for keyword in edu_keywords) or \
                        any(re.search(pattern, line, re.IGNORECASE) for pattern in degree_patterns):
                    education.append(line)
        return education[:3]

    def extract_keywords(self, text):
        text_lower = text.lower()
        words = re.findall(r'\b[a-z]+\b', text_lower)
        relevant_words = []
        for word in words:
            if word in self.job_keywords and len(word) > 3:
                relevant_words.append(word)
            elif word in [skill.lower() for skill in self.all_skills]:
                relevant_words.append(word)
        word_freq = Counter(relevant_words)
        return [{'word': word.title(), 'count': count}
                for word, count in word_freq.most_common(20)]

    def parse_resume(self, file_path, filename):
        file_extension = filename.lower().split('.')[-1]
        if file_extension == 'pdf':
            text = self.extract_text_from_pdf(file_path)
        elif file_extension in ['docx', 'doc']:
            text = self.extract_text_from_docx(file_path)
        elif file_extension == 'txt':
            text = self.extract_text_from_txt(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}")

        if not text.strip():
            raise ValueError("Could not extract text from file")

        return {
            'contact_info': self.extract_contact_info(text),
            'skills': self.extract_skills(text),
            'experience': self.extract_experience(text),
            'education': self.extract_education(text),
            'keywords': self.extract_keywords(text),
            'raw_text': text[:1000]
        }


# Initialize parser and recommender
parser = ResumeParser()
recommender = JobFieldRecommender()


# Routes
@app.route('/')
def index():
    return render_template('index.html', user=current_user if current_user.is_authenticated else None)


@app.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@app.route('/auth/google')
def google_auth():
    if not google:
        return jsonify({'error': 'Google OAuth not configured'}), 400
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def google_callback():
    if not google:
        return jsonify({'error': 'Google OAuth not configured'}), 400
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if user_info:
            user = User.query.filter_by(google_id=user_info['sub']).first()
            if not user:
                user = User(
                    email=user_info['email'],
                    name=user_info['name'],
                    google_id=user_info['sub'],
                    avatar_url=user_info.get('picture')
                )
                db.session.add(user)
            else:
                user.name = user_info['name']
                user.avatar_url = user_info.get('picture')
                user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            return jsonify({'error': 'Failed to get user information'}), 400
    except Exception as e:
        print(f"OAuth callback error: {e}")
        return jsonify({'error': f'Authentication failed: {str(e)}'}), 400


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


# API Routes
@app.route('/api/test', methods=['GET'])
def test_api():
    try:
        resume_count = Resume.query.count()
        user_count = User.query.count()
        result = {
            'success': True,
            'message': 'API is working!',
            'timestamp': datetime.utcnow().isoformat(),
            'database_info': {
                'total_resumes': resume_count,
                'total_users': user_count,
                'oauth_enabled': oauth_enabled,
                'pdf_support': pdf_support,
                'docx_support': docx_support,
                'ats_support': ats_support,
                'fast_ats_support': fast_ats_support
            }
        }
        if current_user.is_authenticated:
            user_resumes = Resume.query.filter_by(user_id=current_user.id).count()
            result['user_info'] = {
                'user_id': current_user.id,
                'user_name': current_user.name,
                'user_resumes': user_resumes
            }
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/user', methods=['GET'])
def get_current_user():
    if current_user.is_authenticated:
        return jsonify({'success': True, 'user': current_user.to_dict()})
    else:
        return jsonify({'success': False, 'message': 'Not authenticated'})


@app.route('/api/upload', methods=['POST'])
def upload_resume():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        allowed_extensions = {'pdf', 'docx', 'doc', 'txt'}
        file_extension = file.filename.lower().split('.')[-1]
        if file_extension not in allowed_extensions:
            return jsonify(
                {'success': False, 'error': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'}), 400

        original_filename = file.filename
        filename = secure_filename(original_filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            parsed_data = parser.parse_resume(file_path, original_filename)

            experience_text = ' '.join(parsed_data['experience']) if parsed_data['experience'] else ''
            job_recommendations = recommender.get_job_recommendations(
                parsed_data['skills'],
                parsed_data['keywords'],
                experience_text
            )

            resume = Resume(
                user_id=current_user.id if current_user.is_authenticated else None,
                filename=filename,
                original_filename=original_filename,
                name=parsed_data['contact_info'].get('name'),
                email=parsed_data['contact_info'].get('email'),
                phone=parsed_data['contact_info'].get('phone'),
                linkedin=parsed_data['contact_info'].get('linkedin'),
                skills=json.dumps(parsed_data['skills']),
                experience=json.dumps(parsed_data['experience']),
                education=json.dumps(parsed_data['education']),
                keywords=json.dumps(parsed_data['keywords']),
                raw_text=parsed_data.get('raw_text', '')
            )

            db.session.add(resume)
            db.session.commit()

            os.remove(file_path)

            return jsonify({
                'success': True,
                'data': {
                    'id': resume.id,
                    'filename': original_filename,
                    'contact_info': parsed_data['contact_info'],
                    'skills': parsed_data['skills'],
                    'experience': parsed_data['experience'],
                    'education': parsed_data['education'],
                    'keywords': parsed_data['keywords'],
                    'job_recommendations': job_recommendations
                }
            })

        except Exception as e:
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'success': False, 'error': f'Error parsing resume: {str(e)}'}), 500

    except Exception as e:
        return jsonify({'success': False, 'error': f'Upload error: {str(e)}'}), 500


# Enhanced ATS Job Scraping Routes
@app.route('/api/fetch-ats-jobs-fast', methods=['POST'])
def fetch_ats_jobs_fast():
    """Fetch jobs using the fast async scraper"""
    if not fast_ats_support:
        return jsonify({
            'success': False,
            'error': 'Fast ATS scraper not available. Please install enhanced_ats_scraper and required packages.'
        }), 400

    try:
        data = request.json
        job_field = data.get('field')
        resume_data = data.get('resume_data', {})
        experience_level = data.get('experience_level')  # 'entry', 'junior', 'mid', 'senior', 'executive'
        location_type = data.get('location_type')  # 'remote', 'onsite', 'hybrid'
        max_jobs = data.get('max_jobs', 200)

        if not job_field:
            return jsonify({'success': False, 'error': 'No job field specified'}), 400

        print(f"Fetching jobs for {job_field} (experience: {experience_level}, location: {location_type})")

        # Use the fast scraper
        jobs = get_jobs_sync(
            job_field=job_field,
            resume_data=resume_data,
            experience_level=experience_level,
            location_type=location_type,
            max_jobs=max_jobs
        )

        return jsonify({
            'success': True,
            'jobs': jobs,
            'total': len(jobs),
            'filters_applied': {
                'experience_level': experience_level,
                'location_type': location_type,
                'max_jobs': max_jobs
            }
        })

    except Exception as e:
        print(f"Error fetching fast ATS jobs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/job-filters', methods=['GET'])
def get_job_filters():
    """Get available filter options"""
    return jsonify({
        'success': True,
        'filters': {
            'experience_levels': [
                {'value': 'entry', 'label': 'Entry Level (0-2 years)'},
                {'value': 'junior', 'label': 'Junior (1-3 years)'},
                {'value': 'mid', 'label': 'Mid Level (3-5 years)'},
                {'value': 'senior', 'label': 'Senior (5+ years)'},
                {'value': 'executive', 'label': 'Executive/Leadership'}
            ],
            'location_types': [
                {'value': 'remote', 'label': 'Remote Only'},
                {'value': 'onsite', 'label': 'On-site Only'},
                {'value': 'hybrid', 'label': 'Hybrid'}
            ],
            'job_types': [
                {'value': 'fulltime', 'label': 'Full-time'},
                {'value': 'parttime', 'label': 'Part-time'},
                {'value': 'contract', 'label': 'Contract'},
                {'value': 'internship', 'label': 'Internship'}
            ]
        }
    })


@app.route('/api/companies-count', methods=['GET'])
def get_companies_count():
    """Get count of companies being scraped"""
    if not fast_ats_support:
        return jsonify({'success': False, 'error': 'Fast ATS scraper not available'}), 400

    try:
        from enhanced_ats_scraper import FastATSJobScraper
        scraper = FastATSJobScraper()

        return jsonify({
            'success': True,
            'total_companies': len(scraper.companies),
            'companies': [{'name': c['name'], 'type': c.get('type', 'generic')} for c in scraper.companies[:10]]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Fallback to original scraper
@app.route('/api/fetch-ats-jobs', methods=['POST'])
def fetch_ats_jobs():
    """Fallback to old scraper or redirect to fast scraper"""
    if fast_ats_support:
        # Redirect to fast scraper
        return fetch_ats_jobs_fast()

    # Keep the old implementation as fallback
    if not ats_support:
        return jsonify(
            {'success': False, 'error': 'ATS scraper not available. Please install ollama and required packages.'}), 400

    try:
        data = request.json
        job_field = data.get('field')
        resume_data = data.get('resume_data', {})

        if not job_field:
            return jsonify({'success': False, 'error': 'No job field specified'}), 400

        # Get personalized jobs using old scraper
        jobs = job_service.get_personalized_jobs(job_field, resume_data)

        return jsonify({
            'success': True,
            'jobs': jobs,
            'total': len(jobs)
        })

    except Exception as e:
        print(f"Error fetching ATS jobs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/resumes', methods=['GET'])
@login_required
def get_resumes():
    try:
        resumes = Resume.query.filter_by(user_id=current_user.id).order_by(Resume.upload_date.desc()).all()
        return jsonify({
            'success': True,
            'resumes': [resume.to_dict() for resume in resumes]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/resumes/<int:resume_id>', methods=['DELETE'])
@login_required
def delete_resume(resume_id):
    try:
        resume = Resume.query.filter_by(id=resume_id, user_id=current_user.id).first()
        if not resume:
            return jsonify({'success': False, 'error': 'Resume not found'}), 404

        db.session.delete(resume)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Resume deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500


# Create database tables
with app.app_context():
    try:
        db.create_all()
        print("✅ Database tables created successfully!")
        resume_count = Resume.query.count()
        user_count = User.query.count()
        print(f"📊 Database Status: {resume_count} resumes, {user_count} users")
        print(f"📄 PDF Support: {'✅ Enabled' if pdf_support else '❌ Disabled'}")
        print(f"📝 DOCX Support: {'✅ Enabled' if docx_support else '❌ Disabled'}")
        print(f"🔐 OAuth: {'✅ Enabled' if oauth_enabled else '❌ Disabled'}")
        print(f"🎯 ATS Scraper: {'✅ Enabled' if ats_support else '❌ Disabled'}")
        print(f"🚀 Fast ATS Scraper: {'✅ Enabled' if fast_ats_support else '❌ Disabled'}")
    except Exception as e:
        print(f"❌ Error creating database: {e}")

if __name__ == '__main__':
    print("\n🚀 Starting Resume Parser Application with Enhanced ATS Scraper")
    print("📍 Visit: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5000)