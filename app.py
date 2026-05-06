import json
import logging
import os
import re
import tempfile
from collections import Counter
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()

oauth = None
google = None
oauth_enabled = False


try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PyPDF2 = None
    PDF_SUPPORT = False

try:
    import docx
    DOCX_SUPPORT = True
except ImportError:
    docx = None
    DOCX_SUPPORT = False

try:
    from enhanced_ats_scraper import get_jobs_sync, get_skill_gap_analysis
    ENHANCED_ATS_SUPPORT = True
except Exception as exc:
    logger.warning("Enhanced ATS scraper unavailable: %s", exc)
    ENHANCED_ATS_SUPPORT = False

    def get_jobs_sync(job_field, resume_data, **kwargs):
        return []

    def get_skill_gap_analysis(resume_data, job_description):
        return {
            "success": True,
            "engine": "fallback",
            "analysis": {
                "overall_fit": "unknown",
                "matching_skills": [],
                "missing_skills": [],
                "resume_bullet_improvements": [],
                "interview_talking_points": [],
            },
        }


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:///resume_parser.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))

    cors_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5000,https://jobsniffr.onrender.com",
    ).split(",")

    CORS(app, origins=cors_origins, supports_credentials=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"

    configure_oauth(app)
    register_routes(app)

    with app.app_context():
        db.create_all()

    return app


def configure_oauth(app):
    global oauth, google, oauth_enabled

    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not google_client_id or not google_client_secret:
        logger.warning("Google OAuth not configured")
        return

    try:
        from authlib.integrations.flask_client import OAuth

        oauth = OAuth(app)
        google = oauth.register(
            name="google",
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
                "prompt": "select_account",
            },
        )

        oauth_enabled = True
        logger.info("Google OAuth enabled")

    except Exception as exc:
        logger.exception("OAuth setup failed: %s", exc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    avatar_url = db.Column(db.String(300))
    google_id = db.Column(db.String(120), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)

    resumes = db.relationship(
        "Resume", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    applications = db.relationship(
        "Application", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "avatar_url": self.avatar_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resume_count": len(self.resumes),
        }


class Resume(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    linkedin = db.Column(db.String(255))

    skills = db.Column(db.Text)
    experience = db.Column(db.Text)
    education = db.Column(db.Text)
    keywords = db.Column(db.Text)
    raw_text = db.Column(db.Text)

    def to_dict(self, include_raw_text=False):
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "upload_date": self.upload_date.isoformat() if self.upload_date else None,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "linkedin": self.linkedin,
            "skills": json.loads(self.skills) if self.skills else [],
            "experience": json.loads(self.experience) if self.experience else [],
            "education": json.loads(self.education) if self.education else [],
            "keywords": json.loads(self.keywords) if self.keywords else [],
        }

        if include_raw_text:
            data["raw_text"] = self.raw_text

        return data


class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    job_id = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255))
    url = db.Column(db.Text)
    status = db.Column(db.String(50), default="Saved")
    match_score = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "status": self.status,
            "match_score": self.match_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class ResumeParser:
    def __init__(self):
        self.skills = [
            "Python", "Java", "JavaScript", "TypeScript", "React", "Node.js",
            "Flask", "FastAPI", "Django", "HTML", "CSS", "SQL", "PostgreSQL",
            "MySQL", "SQLite", "MongoDB", "Redis", "AWS", "Azure", "Docker",
            "Kubernetes", "Git", "GitHub", "CI/CD", "Linux", "REST API",
            "GraphQL", "Machine Learning", "TensorFlow", "PyTorch", "Pandas",
            "NumPy", "Spark", "Databricks", "Snowflake", "Ollama", "LLM",
            "NLP", "Hugging Face",
        ]

        self.keywords = [
            "software", "engineer", "developer", "backend", "frontend",
            "full-stack", "api", "cloud", "database", "automation",
            "deployment", "monitoring", "testing", "agile", "scrum",
            "data", "pipeline", "analytics",
        ]

    def parse_resume(self, file_path, filename):
        ext = filename.lower().rsplit(".", 1)[-1]

        if ext == "pdf":
            text = self.extract_pdf(file_path)
        elif ext in {"docx", "doc"}:
            text = self.extract_docx(file_path)
        elif ext == "txt":
            text = self.extract_txt(file_path)
        else:
            raise ValueError("Unsupported file type")

        text = self.clean_text(text)

        if not text:
            raise ValueError("Could not extract text from resume")

        return {
            "contact_info": self.extract_contact_info(text),
            "skills": self.extract_skills(text),
            "experience": self.extract_experience(text),
            "education": self.extract_education(text),
            "keywords": self.extract_keywords(text),
            "raw_text": text[:8000],
        }

    def extract_pdf(self, file_path):
        if not PDF_SUPPORT:
            raise ValueError("PDF support unavailable")

        text = []
        with open(file_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text.append(page.extract_text() or "")

        return "\n".join(text)

    def extract_docx(self, file_path):
        if not DOCX_SUPPORT:
            raise ValueError("DOCX support unavailable")

        document = docx.Document(file_path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    def extract_txt(self, file_path):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            return file.read()

    def clean_text(self, text):
        text = re.sub(r"\r", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def extract_contact_info(self, text):
        contact = {}

        email = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
        if email:
            contact["email"] = email.group(0)

        phone = re.search(r"(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}", text)
        if phone:
            contact["phone"] = phone.group(0)

        linkedin = re.search(
            r"(https?://)?(www\.)?linkedin\.com/in/[A-Za-z0-9_-]+",
            text,
            re.IGNORECASE,
        )
        if linkedin:
            contact["linkedin"] = linkedin.group(0)

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:8]:
            lower = line.lower()
            if any(word in lower for word in ["resume", "summary", "education", "experience"]):
                continue
            if "@" in line or "linkedin" in lower or re.search(r"\d{3}", line):
                continue
            if 2 <= len(line.split()) <= 4 and len(line) <= 60:
                contact["name"] = line
                break

        return contact

    def extract_skills(self, text):
        found = set()
        lower = text.lower()

        for skill in self.skills:
            pattern = r"(?<![A-Za-z0-9+#.])" + re.escape(skill.lower()) + r"(?![A-Za-z0-9+#.])"
            if re.search(pattern, lower):
                found.add(skill)

        return sorted(found)

    def extract_experience(self, text):
        section = self.extract_section(
            text,
            ["experience", "work experience", "employment"],
            ["education", "skills", "projects", "certifications"],
        )
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        return lines[:12]

    def extract_education(self, text):
        section = self.extract_section(
            text,
            ["education"],
            ["experience", "skills", "projects", "certifications"],
        )

        target = section if section else text
        lines = [line.strip() for line in target.splitlines() if line.strip()]

        terms = [
            "bachelor", "master", "phd", "associate", "university",
            "college", "b.s.", "b.a.", "m.s.", "computer science",
        ]

        return [line for line in lines if any(term in line.lower() for term in terms)][:6]

    def extract_section(self, text, start_terms, end_terms):
        lines = text.splitlines()
        capture = False
        captured = []

        for line in lines:
            lower = line.strip().lower()

            if not capture and any(term == lower or term in lower for term in start_terms):
                capture = True
                continue

            if capture and any(term == lower or term in lower for term in end_terms):
                break

            if capture:
                captured.append(line)

        return "\n".join(captured)

    def extract_keywords(self, text):
        lower = text.lower()
        words = re.findall(r"\b[a-zA-Z][a-zA-Z+#.]{2,}\b", lower)

        relevant = [word for word in words if word in [k.lower() for k in self.keywords]]
        counts = Counter(relevant)

        return [{"word": word, "count": count} for word, count in counts.most_common(25)]


class JobFieldRecommender:
    def __init__(self):
        self.job_fields = {
            "Software Engineer": ["Python", "Java", "JavaScript", "React", "Flask", "SQL", "Git"],
            "Backend Engineer": ["Python", "Java", "Flask", "FastAPI", "PostgreSQL", "Redis", "Docker"],
            "Data Engineer": ["Python", "SQL", "Spark", "Databricks", "Snowflake", "AWS"],
            "DevOps Engineer": ["Docker", "Kubernetes", "AWS", "Linux", "CI/CD", "Terraform"],
            "AI Application Engineer": ["Python", "Ollama", "LLM", "NLP", "Hugging Face", "FastAPI"],
        }

    def get_job_recommendations(self, skills, keywords, experience_text=""):
        user_skills = {skill.lower() for skill in skills}
        results = []

        for field, required_skills in self.job_fields.items():
            required = {skill.lower() for skill in required_skills}
            matched = user_skills.intersection(required)

            score = round((len(matched) / len(required)) * 100) if required else 0

            results.append({
                "field": field,
                "match_percentage": score,
                "matched_skills": sorted(matched),
                "job_search_url": {
                    "linkedin": f"https://www.linkedin.com/jobs/search/?keywords={field.replace(' ', '+')}",
                    "indeed": f"https://www.indeed.com/jobs?q={field.replace(' ', '+')}",
                    "glassdoor": f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={field.replace(' ', '+')}",
                },
            })

        results.sort(key=lambda item: item["match_percentage"], reverse=True)
        return results


resume_parser = ResumeParser()
job_recommender = JobFieldRecommender()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "pdf", "docx", "doc", "txt"
    }


def register_routes(app):
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/login")
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/auth/google")
    def google_auth():
        if not google:
            return jsonify({"success": False, "error": "OAuth not configured"}), 400

        redirect_uri = url_for("google_callback", _external=True)
        return google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def google_callback():
        if not google:
            return jsonify({"success": False, "error": "OAuth not configured"}), 400

        try:
            token = google.authorize_access_token()
            user_info = token.get("userinfo") or google.parse_id_token(token)

            google_id = user_info.get("sub")
            email = user_info.get("email")
            name = user_info.get("name", email)
            picture = user_info.get("picture")

            if not google_id or not email:
                return jsonify({"success": False, "error": "Missing Google user data"}), 400

            user = User.query.filter_by(google_id=google_id).first()

            if not user:
                user = User(
                    email=email,
                    name=name,
                    google_id=google_id,
                    avatar_url=picture,
                )
                db.session.add(user)
            else:
                user.name = name
                user.avatar_url = picture
                user.last_login = datetime.utcnow()

            db.session.commit()
            login_user(user)

            return redirect(url_for("dashboard"))

        except Exception as exc:
            logger.exception("OAuth failed")
            return jsonify({"success": False, "error": str(exc)}), 400

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect(url_for("login"))

    @app.route("/api/user")
    def get_user():
        if current_user.is_authenticated:
            return jsonify({"success": True, "user": current_user.to_dict()})
        return jsonify({"success": False, "message": "Not authenticated"}), 401

    @app.route("/api/test")
    def test():
        return jsonify({
            "success": True,
            "message": "JobSniffr API is running",
            "timestamp": datetime.utcnow().isoformat(),
            "database_info": {
                "total_resumes": Resume.query.count(),
                "total_users": User.query.count(),
                "total_applications": Application.query.count(),
                "oauth_enabled": oauth_enabled,
                "pdf_support": PDF_SUPPORT,
                "docx_support": DOCX_SUPPORT,
                "enhanced_ats_support": ENHANCED_ATS_SUPPORT,
            },
        })

    @app.route("/api/job-filters")
    def job_filters():
        return jsonify({
            "success": True,
            "filters": {
                "experience_levels": [
                    {"value": "entry", "label": "Entry Level / New Grad"},
                    {"value": "junior", "label": "Junior"},
                    {"value": "mid", "label": "Mid Level"},
                    {"value": "senior", "label": "Senior"},
                ],
                "location_types": [
                    {"value": "remote", "label": "Remote"},
                    {"value": "hybrid", "label": "Hybrid"},
                    {"value": "onsite", "label": "On-site"},
                ],
                "job_types": [
                    {"value": "fulltime", "label": "Full-time"},
                    {"value": "contract", "label": "Contract"},
                    {"value": "internship", "label": "Internship"},
                ],
            },
        })

    @app.route("/api/upload", methods=["POST"])
    @login_required
    def upload_resume():
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400

        uploaded_file = request.files["file"]

        if not uploaded_file.filename:
            return jsonify({"success": False, "error": "No file selected"}), 400

        if not allowed_file(uploaded_file.filename):
            return jsonify({"success": False, "error": "Invalid file type"}), 400

        original_filename = uploaded_file.filename
        safe_filename = secure_filename(original_filename)

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{safe_filename}") as temp_file:
                uploaded_file.save(temp_file.name)
                temp_path = temp_file.name

            parsed_data = resume_parser.parse_resume(temp_path, original_filename)

            experience_text = " ".join(parsed_data["experience"])
            job_recommendations = job_recommender.get_job_recommendations(
                parsed_data["skills"],
                parsed_data["keywords"],
                experience_text,
            )

            resume = Resume(
                user_id=current_user.id if current_user.is_authenticated else None,
                filename=safe_filename,
                original_filename=original_filename,
                name=parsed_data["contact_info"].get("name"),
                email=parsed_data["contact_info"].get("email"),
                phone=parsed_data["contact_info"].get("phone"),
                linkedin=parsed_data["contact_info"].get("linkedin"),
                skills=json.dumps(parsed_data["skills"]),
                experience=json.dumps(parsed_data["experience"]),
                education=json.dumps(parsed_data["education"]),
                keywords=json.dumps(parsed_data["keywords"]),
                raw_text=parsed_data["raw_text"],
            )

            db.session.add(resume)
            db.session.commit()

            return jsonify({
                "success": True,
                "data": {
                    "id": resume.id,
                    "filename": original_filename,
                    "contact_info": parsed_data["contact_info"],
                    "skills": parsed_data["skills"],
                    "experience": parsed_data["experience"],
                    "education": parsed_data["education"],
                    "keywords": parsed_data["keywords"],
                    "job_recommendations": job_recommendations,
                },
            })

        except Exception as exc:
            logger.exception("Upload failed")
            return jsonify({"success": False, "error": str(exc)}), 500

        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @app.route("/api/fetch-ats-jobs-fast", methods=["POST"])
    @login_required
    def fetch_ats_jobs_fast():
        payload = request.get_json(silent=True) or {}

        job_field = payload.get("field")
        resume_data = payload.get("resume_data", {})
        experience_level = payload.get("experience_level")
        location_type = payload.get("location_type")
        max_jobs = int(payload.get("max_jobs", 50))

        if not job_field:
            return jsonify({"success": False, "error": "No job field specified"}), 400

        jobs = get_jobs_sync(
            job_field=job_field,
            resume_data=resume_data,
            experience_level=experience_level,
            location_type=location_type,
            max_jobs=max_jobs,
        )

        return jsonify({
            "success": True,
            "jobs": jobs,
            "total": len(jobs),
        })

    @app.route("/api/fetch-ats-jobs", methods=["POST"])
    @login_required
    def fetch_ats_jobs():
        return fetch_ats_jobs_fast()

    @app.route("/api/resumes")
    @login_required
    def list_resumes():
        resumes = (
            Resume.query.filter_by(user_id=current_user.id)
            .order_by(Resume.upload_date.desc())
            .all()
        )
        return jsonify({"success": True, "resumes": [resume.to_dict() for resume in resumes]})

    @app.route("/api/applications", methods=["GET"])
    @login_required
    def list_applications():
        applications = (
            Application.query.filter_by(user_id=current_user.id)
            .order_by(Application.updated_at.desc())
            .all()
        )
        return jsonify({
            "success": True,
            "applications": [application.to_dict() for application in applications],
        })

    @app.route("/api/applications", methods=["POST"])
    @login_required
    def save_application():
        payload = request.get_json(silent=True) or {}

        required = ["job_id", "title", "company"]
        missing = [field for field in required if not payload.get(field)]

        if missing:
            return jsonify({"success": False, "error": f"Missing fields: {missing}"}), 400

        application = Application(
            user_id=current_user.id,
            job_id=payload["job_id"],
            title=payload["title"],
            company=payload["company"],
            location=payload.get("location"),
            url=payload.get("url"),
            status=payload.get("status", "Saved"),
            match_score=int(payload.get("match_score", 0)),
        )

        db.session.add(application)
        db.session.commit()

        return jsonify({"success": True, "application": application.to_dict()})


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_ENV") == "development",
    )