# JobSniffer 

## AI-Powered Resume Parser and Job Recommendation Tool

JobSniffer is a cutting-edge web application that uses AI to parse resumes, extract key information, and provide personalized job recommendations. Built with Flask backend and vanilla JavaScript frontend, it features an intelligent ATS job scraper and comprehensive application tracking system.

![JobSniffer Architecture](diagram.png)

##  Features

###  Core Features
- **AI-Powered Resume Parsing**: Extract contact info, skills, experience, and education from PDF, DOCX, and TXT files
- **Smart Job Recommendations**: Get personalized career field matches based on your skills and experience
- **Real-time Job Search**: Direct integration with company ATS systems (Greenhouse, Lever, Workday, etc.)
- **Application Tracker**: Track job applications with status updates (Saved, Applied, In Progress, Rejected)
- **Advanced Filtering**: Filter jobs by experience level, location type, posting date, and match score

###  Advanced Features
- **Google OAuth Integration**: Secure authentication and profile management
- **Resume Management**: Save and manage multiple resumes with version control
- **Interactive Job Cards**: Hover details and one-click application saving
- **Dark/Light Theme**: Modern UI with theme switching
- **Responsive Design**: Works seamlessly on desktop and mobile devices

###  User Interface
- **Modern Dashboard**: Clean, intuitive interface with tab-based navigation
- **Job Details Popup**: Instant job information without page navigation
- **Application Statistics**: Visual tracking of application progress
- **Real-time Search**: Live job filtering and sorting

## 🏗 Architecture

```
JobSniffer/
├── app.py                     # Main Flask application
├── enhanced_ats_scraper.py    # Advanced job scraping engine
├── templates/
│   ├── index.html            # Landing page
│   ├── login.html            # Authentication page
│   └── dashboard.html        # Main application interface
├── static/
│   └── images/
│       └── logo.png          # Application logo
├── uploads/                  # Temporary file storage
├── resume_parser.db          # SQLite database
├── diagram.png              # Architecture diagram
├── requirements.txt         # Python dependencies
├── .env.example            # Environment variables template
└── README.md               # This file
```

##  Technology Stack

### Backend
- **Python 3.8+**: Core programming language
- **Flask**: Web framework
- **SQLAlchemy**: Database ORM
- **Flask-Login**: Authentication management
- **Authlib**: OAuth integration
- **BeautifulSoup4**: Web scraping
- **PyPDF2/pdfplumber**: PDF processing
- **python-docx**: DOCX processing

### Frontend
- **HTML5/CSS3**: Modern web standards
- **Vanilla JavaScript**: No framework dependencies
- **CSS Grid/Flexbox**: Responsive layouts
- **CSS Custom Properties**: Theme system

### Database
- **SQLite**: Lightweight, file-based database
- **User Management**: Secure user profiles and authentication
- **Resume Storage**: Encrypted resume data with metadata

### AI/ML Integration
- **Ollama**: Local AI model integration (optional)
- **Resume Parsing**: Intelligent text extraction and analysis
- **Job Matching**: AI-powered compatibility scoring

##  Prerequisites

Before installation, ensure you have:

- **Python 3.8 or higher**
- **pip** (Python package installer)
- **Git** (for cloning the repository)
- **Internet connection** (for job scraping and OAuth)

### Optional Dependencies
- **Ollama** (for enhanced AI features)
- **Google Cloud Console** account (for OAuth)

##  Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/jobsniffer.git
cd jobsniffer
```

### 2. Platform-Specific Setup

####  macOS

```bash
# Install Python (if not already installed)
brew install python3

# Create virtual environment
python3 -m venv jobsniffer_env
source jobsniffer_env/bin/activate

# Install dependencies
pip install -r requirements.txt
```

####  Linux (Ubuntu/Debian)

```bash
# Update system packages
sudo apt update

# Install Python and pip (if not already installed)
sudo apt install python3 python3-pip python3-venv

# Create virtual environment
python3 -m venv jobsniffer_env
source jobsniffer_env/bin/activate

# Install dependencies
pip install -r requirements.txt
```

####  Windows

```powershell
# Using PowerShell or Command Prompt

# Create virtual environment
python -m venv jobsniffer_env
jobsniffer_env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Install Required Libraries

Create a `requirements.txt` file with the following dependencies:

```txt
Flask==2.3.3
Flask-CORS==4.0.0
Flask-SQLAlchemy==3.0.5
Flask-Login==0.6.2
Werkzeug==2.3.7
Authlib==1.2.1
requests==2.31.0
SQLAlchemy==2.0.21
PyPDF2==3.0.1
python-docx==0.8.11
pdfplumber==0.10.2
beautifulsoup4==4.12.2
lxml==4.9.3
ollama==0.1.7
python-dotenv==1.0.0
secure==0.3.0
```

Then install:

```bash
pip install -r requirements.txt
```

### 4. Environment Configuration

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# Flask Configuration
SECRET_KEY=your-secret-key-here
FLASK_ENV=development

# Google OAuth (Optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Database
DATABASE_URL=sqlite:///resume_parser.db

# Ollama Configuration (Optional)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=mistral
```

### 5. Database Setup

Initialize the database:

```bash
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized!')"
```

### 6. Optional: Set Up Ollama (for Enhanced AI Features)

#### macOS
```bash
brew install ollama
ollama serve
ollama pull mistral
```

#### Linux
```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve
ollama pull mistral
```

#### Windows
Download from [ollama.ai](https://ollama.ai) and follow the installation guide.

### 7. Optional: Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google+ API
4. Create OAuth 2.0 credentials
5. Add your domain to authorized origins
6. Update `.env` with your credentials

##  Running the Application

### Development Mode

```bash
# Activate virtual environment (if not already active)
# macOS/Linux:
source jobsniffer_env/bin/activate
# Windows:
jobsniffer_env\Scripts\activate

# Run the application
python app.py
```

The application will be available at `http://localhost:5000`

### Production Mode

For production deployment, consider using:

```bash
# Using Gunicorn (recommended)
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Or using Flask's built-in server (not recommended for production)
export FLASK_ENV=production
python app.py
```

##  Usage

### 1. Initial Setup
1. Open `http://localhost:5000` in your browser
2. Sign in with Google (optional) or continue as guest
3. Upload your resume (PDF, DOCX, or TXT format)

### 2. Resume Analysis
- View extracted contact information, skills, and experience
- See AI-generated job field recommendations with match percentages
- Access quick links to major job boards (LinkedIn, Indeed, Glassdoor)

### 3. Job Search
- Click "Find Direct Jobs from Companies" for any recommended field
- Use advanced filters:
  - **Experience Level**: Entry, Junior, Mid, Senior, Executive
  - **Work Type**: Remote, On-site, Hybrid
  - **Posting Date**: Today, Yesterday, Last week, etc.
  - **Match Score**: Minimum compatibility percentage

### 4. Application Tracking
- Save interesting jobs to your application tracker
- Update application status: Saved → Applied → In Progress → Rejected
- View application statistics and filter by status or company
- Track application dates and progress

### 5. Job Details
- Hover over "Details" button for instant job information popup
- View job description, requirements, benefits, and company info
- One-click application links to company career pages

##  Configuration

### File Upload Limits
```python
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
```

### Supported File Types
- **PDF**: `.pdf`
- **Microsoft Word**: `.docx`, `.doc`
- **Plain Text**: `.txt`

### Database Configuration
The application uses SQLite by default. For production, consider PostgreSQL:

```env
DATABASE_URL=postgresql://username:password@localhost/jobsniffer
```

##  Testing

### API Testing
Test the backend API:

```bash
# Test basic connectivity
curl http://localhost:5000/api/test

# Test file upload (replace with actual file)
curl -X POST -F "file=@sample_resume.pdf" http://localhost:5000/api/upload
```

### Manual Testing
1. Upload various resume formats
2. Test job search with different filters
3. Verify application tracking functionality
4. Test OAuth authentication flow

##  Troubleshooting

### Common Issues

#### 1. Import Errors
```bash
# Install missing dependencies
pip install -r requirements.txt

# For PDF support issues
pip install PyPDF2 pdfplumber

# For DOCX support issues
pip install python-docx
```

#### 2. Database Issues
```bash
# Reset database
rm resume_parser.db
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

#### 3. OAuth Issues
- Verify Google Cloud Console configuration
- Check authorized origins and redirect URIs
- Ensure `.env` file has correct credentials

#### 4. File Upload Issues
- Check file size (max 16MB)
- Verify file format is supported
- Ensure uploads directory has write permissions

#### 5. Job Scraping Issues
- Verify internet connection
- Check if Ollama is running (for enhanced features)
- Review rate limiting and respect robots.txt

### Debug Mode
Enable detailed error logging:

```bash
export FLASK_DEBUG=1
export FLASK_ENV=development
python app.py
```

##  Contributing

We welcome contributions! Please follow these guidelines:

### Development Setup
1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit with descriptive messages
5. Push and create a pull request

### Code Style
- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add comments for complex logic
- Write docstrings for functions and classes

### Testing
- Test all new features thoroughly
- Ensure existing functionality isn't broken
- Test on multiple browsers and screen sizes
- Verify database migrations work correctly

##  License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

##  Acknowledgments

- **Flask Community** for the excellent web framework
- **Ollama** for local AI model integration
- **Beautiful Soup** for web scraping capabilities
- **Google** for OAuth integration
- **Open Source Community** for various libraries and tools

##  Support

### Documentation
- [Flask Documentation](https://flask.palletsprojects.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Ollama Documentation](https://ollama.ai/docs)

### Issues
If you encounter any issues:
1. Check the troubleshooting section
2. Search existing [GitHub Issues](https://github.com/yourusername/jobsniffer/issues)
3. Create a new issue with detailed information:
   - Operating system and version
   - Python version
   - Error messages and stack traces
   - Steps to reproduce

### Feature Requests
We welcome feature requests! Please:
1. Check if the feature already exists
2. Search existing issues for similar requests
3. Create a detailed feature request with use cases

##  Roadmap

### Upcoming Features
- [ ] **Resume Builder**: Create professional resumes within the app
- [ ] **Interview Tracker**: Schedule and track interview progress
- [ ] **Salary Analytics**: Market salary data for different positions
- [ ] **Cover Letter Generator**: AI-powered cover letter creation
- [ ] **Job Alerts**: Email notifications for new matching jobs
- [ ] **Company Research**: Integrated company information and reviews
- [ ] **Skills Gap Analysis**: Identify missing skills for target roles
- [ ] **Portfolio Integration**: Link to GitHub, LinkedIn, and personal websites

### Technical Improvements
- [ ] **Docker Support**: Containerized deployment
- [ ] **PostgreSQL Migration**: Production-ready database
- [ ] **Redis Caching**: Improved performance for job searches
- [ ] **API Rate Limiting**: Better handling of external requests
- [ ] **Comprehensive Testing**: Unit and integration tests
- [ ] **CI/CD Pipeline**: Automated testing and deployment
- [ ] **Mobile App**: React Native or Flutter mobile application

---
