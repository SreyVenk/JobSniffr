# enhanced_ats_scraper.py
import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin, urlparse
import ollama
from typing import List, Dict, Optional
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ATSJobScraper:
    """
    Scrapes jobs directly from company ATS systems using Ollama for intelligent parsing
    """

    def __init__(self, ollama_model="mistral"):
        try:
            self.ollama = ollama.Client()
            self.model = ollama_model
            logger.info(f"Initialized Ollama with model: {ollama_model}")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama: {e}")
            raise

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # Common ATS platforms and their patterns
        self.ats_patterns = {
            'greenhouse': {
                'job_board_url': '/jobs',
                'api_endpoint': '/api/job_board/jobs',
                'identifier': 'greenhouse.io'
            },
            'lever': {
                'job_board_url': '/jobs',
                'api_endpoint': '/api/jobs',
                'identifier': 'lever.co'
            },
            'workday': {
                'job_board_url': '/careers',
                'identifier': 'myworkdayjobs.com'
            },
            'bamboo': {
                'job_board_url': '/jobs',
                'identifier': 'bamboohr.com/jobs'
            },
            'ashby': {
                'job_board_url': '/jobs',
                'api_endpoint': '/_openapi/jobs',
                'identifier': 'ashbyhq.com'
            },
            'smartrecruiters': {
                'job_board_url': '/careers',
                'identifier': 'smartrecruiters.com'
            }
        }

        # Tech companies that use ATS (expandable list)
        self.target_companies = [
            {'name': 'Stripe', 'url': 'https://stripe.com/jobs'},
            {'name': 'Datadog', 'url': 'https://careers.datadoghq.com/'},
            {'name': 'Cloudflare', 'url': 'https://www.cloudflare.com/careers/jobs/'},
            {'name': 'HashiCorp', 'url': 'https://www.hashicorp.com/careers/open-positions'},
            {'name': 'GitLab', 'url': 'https://about.gitlab.com/jobs/'},
            {'name': 'Elastic', 'url': 'https://www.elastic.co/careers/jobs'},
            {'name': 'MongoDB', 'url': 'https://www.mongodb.com/careers/jobs'},
            {'name': 'Snowflake', 'url': 'https://careers.snowflake.com/us/en/search-results'},
            {'name': 'Databricks', 'url': 'https://www.databricks.com/company/careers/open-positions'},
            {'name': 'Confluent', 'url': 'https://www.confluent.io/careers/'},
            {'name': 'Twilio', 'url': 'https://www.twilio.com/en-us/company/jobs'},
            {'name': 'Spotify', 'url': 'https://www.lifeatspotify.com/jobs'},
            {'name': 'Shopify', 'url': 'https://www.shopify.com/careers/search'},
            {'name': 'Square', 'url': 'https://careers.squareup.com/us/en/jobs'},
            {'name': 'Zoom', 'url': 'https://careers.zoom.us/jobs/'},
        ]

    def detect_ats_type(self, url: str) -> Optional[str]:
        """Detect which ATS system a company is using"""
        for ats_name, pattern in self.ats_patterns.items():
            if pattern['identifier'] in url:
                return ats_name

        # Check page content for ATS signatures
        try:
            response = self.session.get(url, timeout=10)
            content = response.text.lower()

            if 'greenhouse' in content or 'boards.greenhouse.io' in content:
                return 'greenhouse'
            elif 'lever.co' in content:
                return 'lever'
            elif 'myworkdayjobs' in content:
                return 'workday'
            elif 'ashbyhq' in content:
                return 'ashby'

        except Exception as e:
            logger.error(f"Error detecting ATS for {url}: {e}")

        return None

    def scrape_greenhouse(self, company_url: str) -> List[Dict]:
        """Scrape jobs from Greenhouse ATS"""
        jobs = []

        # Try API endpoint first
        domain = urlparse(company_url).netloc
        company_name = domain.split('.')[0]
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_name}/jobs"

        try:
            response = self.session.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for job in data.get('jobs', []):
                    jobs.append({
                        'title': job.get('title'),
                        'department': job.get('departments', [{}])[0].get('name', ''),
                        'location': job.get('location', {}).get('name', ''),
                        'url': job.get('absolute_url'),
                        'id': job.get('id'),
                        'company': company_name,
                        'ats': 'greenhouse'
                    })
                logger.info(f"Found {len(jobs)} jobs from Greenhouse API for {company_name}")
        except Exception as e:
            logger.error(f"Error scraping Greenhouse API: {e}")
            # Fallback to HTML scraping
            jobs = self.scrape_html_jobs(company_url)

        return jobs

    def scrape_lever(self, company_url: str) -> List[Dict]:
        """Scrape jobs from Lever ATS"""
        jobs = []

        # Extract company name from URL
        if 'lever.co' in company_url:
            company_name = urlparse(company_url).netloc.split('.')[0]
        else:
            # Try to extract from the URL path
            company_name = company_url.split('/')[-1] or 'company'

        api_url = f"https://api.lever.co/v0/postings/{company_name}"

        try:
            response = self.session.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for job in data:
                    jobs.append({
                        'title': job.get('text'),
                        'department': job.get('categories', {}).get('department', ''),
                        'location': job.get('categories', {}).get('location', ''),
                        'url': job.get('hostedUrl'),
                        'id': job.get('id'),
                        'company': company_name,
                        'ats': 'lever'
                    })
                logger.info(f"Found {len(jobs)} jobs from Lever API for {company_name}")
        except Exception as e:
            logger.error(f"Error scraping Lever API: {e}")
            jobs = self.scrape_html_jobs(company_url)

        return jobs

    def scrape_html_jobs(self, url: str) -> List[Dict]:
        """Fallback HTML scraping when API is not available"""
        jobs = []

        try:
            # Add delay to be respectful
            time.sleep(random.uniform(1, 3))

            response = self.session.get(url, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find potential job listings in the HTML
            job_containers = soup.find_all(['div', 'section', 'article', 'li'],
                                           class_=re.compile('job|position|opening|career', re.I))

            if not job_containers:
                # Try to find any links that look like job postings
                job_links = soup.find_all('a', href=re.compile('job|position|career|opening', re.I))
                job_containers = job_links[:20]  # Limit to prevent too much processing

            # Use Ollama to extract job information
            if job_containers:
                html_snippet = str(job_containers[:10])  # Process first 10 items

                prompt = f"""
                Extract job listings from this HTML. Return a JSON array where each job has:
                - title: job title
                - department: department or team (or empty string if not found)
                - location: job location (or "Remote" if remote)
                - url: relative URL path to the job (starting with /)

                HTML:
                {html_snippet[:4000]}

                Return ONLY a valid JSON array, no other text. Example:
                [
                    {{"title": "Software Engineer", "department": "Engineering", "location": "San Francisco", "url": "/jobs/123"}},
                    {{"title": "Data Scientist", "department": "Data", "location": "Remote", "url": "/jobs/124"}}
                ]
                """

                try:
                    response = self.ollama.generate(model=self.model, prompt=prompt)
                    response_text = response['response']

                    # Try to extract JSON from the response
                    json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                    if json_match:
                        extracted_jobs = json.loads(json_match.group())

                        for job in extracted_jobs:
                            if job.get('url'):
                                job['url'] = urljoin(url, job['url'])
                            job['company'] = urlparse(url).netloc.split('.')[0]
                            job['ats'] = 'unknown'
                            jobs.append(job)

                        logger.info(f"Extracted {len(jobs)} jobs using Ollama from {url}")
                except Exception as e:
                    logger.error(f"Failed to parse Ollama response: {e}")

        except Exception as e:
            logger.error(f"Error in HTML scraping for {url}: {e}")

        return jobs

    def extract_job_details(self, job_url: str) -> Dict:
        """Use Ollama to extract detailed information from a job posting"""
        try:
            time.sleep(random.uniform(1, 2))  # Rate limiting

            response = self.session.get(job_url, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')

            # Remove script and style elements
            for script in soup(['script', 'style']):
                script.decompose()

            text = soup.get_text()
            # Limit text to prevent token overflow
            text = text[:5000]

            prompt = f"""
            Extract the following information from this job posting. Return as JSON:
            - required_skills: array of technical skills that are required
            - nice_to_have_skills: array of optional/preferred skills
            - experience_years: minimum years of experience required (number or null)
            - job_type: "Full-time", "Part-time", "Contract", or "Not specified"
            - remote_friendly: "Remote", "Hybrid", "On-site", or "Not specified"
            - salary_range: salary if mentioned (string) or null

            Job posting:
            {text[:3000]}

            Return ONLY valid JSON. Example:
            {{"required_skills": ["Python", "SQL"], "nice_to_have_skills": ["AWS"], "experience_years": 3, "job_type": "Full-time", "remote_friendly": "Remote", "salary_range": "$120k-150k"}}
            """

            response = self.ollama.generate(model=self.model, prompt=prompt)
            response_text = response['response']

            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                details = json.loads(json_match.group())
                return details

            return {}

        except Exception as e:
            logger.error(f"Error extracting job details from {job_url}: {e}")
            return {}

    def match_job_to_resume(self, job: Dict, resume_data: Dict) -> Dict:
        """Use Ollama to calculate match between job and resume"""
        prompt = f"""
        Calculate how well this resume matches the job. Return JSON with:
        - match_score: percentage from 0-100
        - matching_skills: array of skills from resume that match the job
        - missing_skills: array of required skills not in resume
        - recommendation: one sentence advice for the applicant

        Resume Skills: {', '.join(resume_data.get('skills', [])[:20])}
        Resume Keywords: {', '.join([k['word'] for k in resume_data.get('keywords', [])[:10]])}

        Job Title: {job.get('title')}
        Job Department: {job.get('department')}
        Job Location: {job.get('location')}
        Job Skills: {job.get('required_skills', [])}

        Return ONLY valid JSON. Example:
        {{"match_score": 75, "matching_skills": ["Python", "SQL"], "missing_skills": ["Kubernetes"], "recommendation": "Strong match, consider learning Kubernetes to improve chances."}}
        """

        try:
            response = self.ollama.generate(model=self.model, prompt=prompt)
            response_text = response['response']

            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                match_data = json.loads(json_match.group())
                return match_data

            return {'match_score': 0}

        except Exception as e:
            logger.error(f"Error in job matching: {e}")
            return {'match_score': 0}

    def scrape_company_jobs(self, company: Dict, job_field: str) -> List[Dict]:
        """Scrape jobs from a single company"""
        logger.info(f"Scraping {company['name']} for {job_field} positions...")

        ats_type = self.detect_ats_type(company['url'])

        if ats_type == 'greenhouse':
            jobs = self.scrape_greenhouse(company['url'])
        elif ats_type == 'lever':
            jobs = self.scrape_lever(company['url'])
        else:
            # Use generic HTML scraping with Ollama
            jobs = self.scrape_html_jobs(company['url'])

        # Add company name to all jobs
        for job in jobs:
            job['company_name'] = company['name']

        return jobs

    def is_relevant_job(self, job: Dict, job_field: str) -> bool:
        """Check if a job is relevant to the desired field"""
        title_lower = job.get('title', '').lower()
        dept_lower = job.get('department', '').lower()

        # Define keywords for each field
        field_keywords = {
            'Software Engineer': ['software', 'engineer', 'developer', 'backend', 'frontend', 'full stack',
                                  'full-stack', 'swe'],
            'Data Scientist': ['data scientist', 'machine learning', 'ml engineer', 'ai', 'data science'],
            'Data Engineer': ['data engineer', 'etl', 'pipeline', 'data platform', 'data infrastructure'],
            'DevOps Engineer': ['devops', 'sre', 'infrastructure', 'platform engineer', 'site reliability'],
            'Cloud Architect': ['cloud', 'architect', 'solutions architect', 'cloud engineer'],
            'Full Stack Developer': ['full stack', 'full-stack', 'fullstack', 'web developer'],
            'Mobile Developer': ['mobile', 'ios', 'android', 'react native', 'flutter'],
            'Machine Learning Engineer': ['machine learning', 'ml engineer', 'deep learning', 'ai engineer'],
            'Business Analyst': ['business analyst', 'business intelligence', 'bi analyst', 'data analyst'],
            'QA Engineer': ['qa', 'quality', 'test', 'sdet', 'automation engineer'],
        }

        keywords = field_keywords.get(job_field, [job_field.lower()])

        for keyword in keywords:
            if keyword in title_lower or keyword in dept_lower:
                return True

        return False

    def scrape_all_companies(self, job_field: str, resume_data: Dict, max_jobs: int = 50) -> List[Dict]:
        """Scrape jobs from all target companies for a specific field"""
        all_jobs = []

        with ThreadPoolExecutor(max_workers=3) as executor:  # Reduced workers to be respectful
            future_to_company = {}

            for company in self.target_companies:
                future = executor.submit(self.scrape_company_jobs, company, job_field)
                future_to_company[future] = company

            for future in as_completed(future_to_company):
                company = future_to_company[future]
                try:
                    jobs = future.result()

                    # Filter and score jobs based on field and resume
                    for job in jobs:
                        if self.is_relevant_job(job, job_field):
                            # Calculate match score
                            job['match'] = self.match_job_to_resume(job, resume_data)
                            all_jobs.append(job)

                            # Stop if we have enough jobs
                            if len(all_jobs) >= max_jobs * 2:  # Get extra to sort
                                break

                except Exception as e:
                    logger.error(f"Error processing {company['name']}: {e}")

        # Sort by match score
        all_jobs.sort(key=lambda x: x.get('match', {}).get('match_score', 0), reverse=True)

        # Return top matches
        return all_jobs[:max_jobs]


# Service class for integration with Flask
class JobRecommendationService:
    """Service to integrate ATS scraping with your existing app"""

    def __init__(self):
        self.scraper = ATSJobScraper()
        self.cache = {}  # Simple in-memory cache
        self.cache_duration = 3600  # 1 hour

    def get_personalized_jobs(self, job_field: str, resume_data: Dict) -> List[Dict]:
        """Get personalized job recommendations"""

        # Check cache first
        cache_key = f"{job_field}_{hash(str(resume_data.get('skills', [])))})"
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_duration:
                logger.info(f"Returning cached jobs for {job_field}")
                return cached_data

        # Scrape fresh data
        logger.info(f"Scraping fresh jobs for {job_field}")
        jobs = self.scraper.scrape_all_companies(job_field, resume_data, max_jobs=30)

        # Format for frontend
        formatted_jobs = []
        for job in jobs:
            formatted_jobs.append({
                'title': job.get('title'),
                'company': job.get('company_name'),
                'location': job.get('location', 'Not specified'),
                'url': job.get('url'),
                'match_score': job.get('match', {}).get('match_score', 0),
                'matching_skills': job.get('match', {}).get('matching_skills', []),
                'missing_skills': job.get('match', {}).get('missing_skills', []),
                'recommendation': job.get('match', {}).get('recommendation', ''),
                'department': job.get('department', ''),
                'ats_type': job.get('ats', 'Unknown')
            })

        # Cache the results
        self.cache[cache_key] = (formatted_jobs, time.time())

        return formatted_jobs


from dataclasses import dataclass

@dataclass
class JobListing:
    """Data class for job listings"""
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    department: str = ""
    experience_level: str = ""
    job_type: str = "Full-time"
    remote_type: str = "Not specified"
    salary_range: str = ""
    posted_date: str = ""
    required_skills: list = None
    nice_to_have_skills: list = None
    ats_type: str = "unknown"
    company_size: str = ""
    industry: str = ""

    def __post_init__(self):
        if self.required_skills is None:
            self.required_skills = []
        if self.nice_to_have_skills is None:
            self.nice_to_have_skills = []


class JobCache:
    """Simple in-memory cache for jobs"""

    def __init__(self):
        self.cache = {}
        self.cache_duration = 3600  # 1 hour

    def get_cached_jobs(self, job_field: str, max_age_hours: int = 1) -> list:
        """Get cached jobs that are still fresh"""
        cache_key = f"{job_field}"
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_duration:
                logger.info(f"Returning cached jobs for {job_field}")
                return cached_data
        return []

    def cache_jobs(self, jobs: list, job_field: str):
        """Cache jobs in memory"""
        cache_key = f"{job_field}"
        self.cache[cache_key] = (jobs, time.time())


class FastATSJobScraper:
    """High-performance ATS scraper"""

    def __init__(self, ollama_model="mistral"):
        try:
            self.ollama = ollama.Client()
            self.model = ollama_model
            logger.info(f"Initialized Ollama with model: {ollama_model}")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama: {e}")
            # Continue without Ollama - use simple matching
            self.ollama = None
            self.model = None

        self.cache = JobCache()

        # Expanded list of companies with their job board URLs
        self.companies = [
            # Tech Giants
            {"name": "Google", "url": "https://careers.google.com/jobs/results/", "api": False},
            {"name": "Microsoft", "url": "https://careers.microsoft.com/us/en/search-results", "api": False},
            {"name": "Amazon", "url": "https://www.amazon.jobs/en/search", "api": False},
            {"name": "Meta", "url": "https://www.metacareers.com/jobs", "api": False},
            {"name": "Apple", "url": "https://jobs.apple.com/en-us/search", "api": False},

            # High-Growth Companies
            {"name": "Stripe", "url": "https://stripe.com/jobs", "api": False},
            {"name": "Coinbase", "url": "https://www.coinbase.com/careers/positions", "api": False},
            {"name": "Databricks", "url": "https://www.databricks.com/company/careers/open-positions", "api": False},
            {"name": "Snowflake", "url": "https://careers.snowflake.com/us/en/search-results", "api": False},
            {"name": "Palantir", "url": "https://jobs.lever.co/palantir", "api": True, "type": "lever"},
            {"name": "Airbnb", "url": "https://careers.airbnb.com/", "api": False},
            {"name": "Uber", "url": "https://www.uber.com/careers/list/", "api": False},
            {"name": "Lyft", "url": "https://www.lyft.com/careers", "api": False},

            # More companies with direct APIs
            {"name": "Shopify", "url": "https://www.shopify.com/careers", "api": False},
            {"name": "GitLab", "url": "https://about.gitlab.com/jobs/", "api": False},
            {"name": "MongoDB", "url": "https://www.mongodb.com/careers", "api": False},
            {"name": "Zoom", "url": "https://careers.zoom.us/jobs/", "api": False},
            {"name": "Slack", "url": "https://slack.com/careers", "api": False},
            {"name": "Square", "url": "https://careers.squareup.com/us/en/jobs", "api": False},
            {"name": "Robinhood", "url": "https://robinhood.com/careers/", "api": False},
            {"name": "HashiCorp", "url": "https://www.hashicorp.com/jobs", "api": False},
            {"name": "Docker", "url": "https://www.docker.com/careers/", "api": False},
            {"name": "Redis", "url": "https://redis.com/company/careers/", "api": False},
            {"name": "OpenAI", "url": "https://openai.com/careers", "api": False},
            {"name": "Scale AI", "url": "https://scale.com/careers", "api": False},
            {"name": "Unity", "url": "https://careers.unity.com/", "api": False},
            {"name": "Netflix", "url": "https://jobs.netflix.com/", "api": False},
            {"name": "Spotify", "url": "https://www.lifeatspotify.com/jobs", "api": False},
        ]

        # Experience level mapping
        self.experience_levels = {
            "entry": ["intern", "entry", "junior", "associate", "new grad", "graduate", "0-2 years"],
            "junior": ["junior", "associate", "1-3 years", "2-4 years"],
            "mid": ["mid", "senior", "3-5 years", "4-7 years", "experienced"],
            "senior": ["senior", "lead", "principal", "staff", "5+ years", "7+ years"],
            "executive": ["director", "vp", "head of", "chief", "executive", "manager"]
        }

    def is_relevant_job(self, job_title: str, job_field: str) -> bool:
        """Check if a job is relevant to the desired field"""
        title_lower = job_title.lower()

        field_keywords = {
            'Software Engineer': ['software', 'engineer', 'developer', 'backend', 'frontend', 'full stack',
                                  'full-stack', 'swe'],
            'Data Scientist': ['data scientist', 'machine learning', 'ml engineer', 'ai', 'data science'],
            'Data Engineer': ['data engineer', 'etl', 'pipeline', 'data platform', 'data infrastructure'],
            'DevOps Engineer': ['devops', 'sre', 'infrastructure', 'platform engineer', 'site reliability'],
            'Cloud Architect': ['cloud', 'architect', 'solutions architect', 'cloud engineer'],
            'Full Stack Developer': ['full stack', 'full-stack', 'fullstack', 'web developer'],
            'Mobile Developer': ['mobile', 'ios', 'android', 'react native', 'flutter'],
            'Machine Learning Engineer': ['machine learning', 'ml engineer', 'deep learning', 'ai engineer'],
            'Business Analyst': ['business analyst', 'business intelligence', 'bi analyst', 'data analyst'],
            'QA Engineer': ['qa', 'quality', 'test', 'sdet', 'automation engineer'],
        }

        keywords = field_keywords.get(job_field, [job_field.lower()])
        return any(keyword in title_lower for keyword in keywords)

    def extract_experience_level(self, job_title: str) -> str:
        """Extract experience level from job title"""
        title_lower = job_title.lower()

        for level, keywords in self.experience_levels.items():
            if any(keyword in title_lower for keyword in keywords):
                return level

        return "mid"  # Default to mid-level

    # Add this to your enhanced_ats_scraper.py file, replacing the generate_mock_jobs method

    def generate_mock_jobs(self, job_field: str, resume_data: dict) -> list:
        """Generate realistic mock jobs with fresh posting dates"""
        companies = [
            "Google", "Microsoft", "Amazon", "Meta", "Apple", "Stripe", "Databricks",
            "Snowflake", "Airbnb", "Uber", "Netflix", "Spotify", "Shopify", "GitHub",
            "GitLab", "MongoDB", "Redis", "Docker", "OpenAI", "Anthropic", "Scale AI",
            "Coinbase", "Robinhood", "Square", "Zoom", "Slack", "Atlassian", "Figma"
        ]

        locations = [
            "Remote", "San Francisco, CA", "New York, NY", "Seattle, WA",
            "Austin, TX", "Boston, MA", "Los Angeles, CA", "Chicago, IL",
            "Denver, CO", "Portland, OR", "Atlanta, GA", "Miami, FL"
        ]

        # Generate posting dates from today back to 30 days
        from datetime import datetime, timedelta
        today = datetime.now()
        posting_dates = []

        # More recent jobs (70% within last week)
        for i in range(20):
            if i < 14:  # 70% within last week
                days_ago = random.randint(0, 7)
            elif i < 18:  # 20% within last 2 weeks
                days_ago = random.randint(8, 14)
            else:  # 10% within last month
                days_ago = random.randint(15, 30)

            post_date = today - timedelta(days=days_ago)
            posting_dates.append(post_date)

        job_titles = [
            f'Senior {job_field}',
            f'Staff {job_field}',
            f'Principal {job_field}',
            f'Lead {job_field}',
            f'{job_field} - Remote',
            f'{job_field} II',
            f'{job_field} III',
            f'Senior Full Stack Engineer' if 'Software' in job_field else f'Senior {job_field}',
            f'{job_field} Manager',
            f'Head of {job_field}',
            f'{job_field} Architect',
            f'{job_field} Specialist',
            f'{job_field} Expert',
            f'{job_field} Consultant',
            f'Remote {job_field}',
            f'{job_field} - New Grad',
            f'Junior {job_field}',
            f'{job_field} Intern',
            f'{job_field} - Contract',
            f'{job_field} - Part Time'
        ]

        departments = [
            'Engineering', 'Product Engineering', 'Platform Engineering',
            'Data Engineering', 'ML Engineering', 'Infrastructure', 'Security',
            'Developer Tools', 'AI Research', 'Cloud Platform', 'Backend Systems'
        ]

        mock_jobs = []
        for i in range(20):  # Generate 20 fresh jobs
            company = companies[i % len(companies)]
            location = locations[i % len(locations)]
            post_date = posting_dates[i]

            # Create more realistic job URLs
            job_id = random.randint(100000, 999999)
            company_slug = company.lower().replace(' ', '')
            job_url = f'https://{company_slug}.com/careers/jobs/{job_id}'

            # More realistic salary ranges based on experience level
            experience_levels = ['entry', 'junior', 'mid', 'senior', 'executive']
            exp_level = experience_levels[i % len(experience_levels)]

            salary_ranges = {
                'entry': ['$70k-90k', '$65k-85k', '$75k-95k'],
                'junior': ['$85k-110k', '$90k-115k', '$80k-105k'],
                'mid': ['$110k-150k', '$120k-160k', '$115k-155k'],
                'senior': ['$150k-220k', '$160k-240k', '$145k-210k'],
                'executive': ['$220k-350k', '$250k-400k', '$200k-320k']
            }

            job = {
                'id': f'job_{job_id}_{job_field.replace(" ", "_")}',
                'title': job_titles[i % len(job_titles)],
                'company': company,
                'location': location,
                'url': job_url,
                'match_score': random.randint(65, 98),
                'experience_level': exp_level,
                'department': departments[i % len(departments)],
                'ats_type': ['lever', 'greenhouse', 'workday', 'bamboo', 'ashby'][i % 5],
                'job_type': 'Full-time' if i % 10 != 9 else ['Part-time', 'Contract', 'Internship'][i % 3],
                'remote_type': 'Remote' if 'Remote' in location else 'Hybrid' if i % 3 == 0 else 'On-site',
                'salary_range': salary_ranges[exp_level][i % 3],
                'posted_date': post_date.strftime('%Y-%m-%d'),
                'posted_days_ago': (today - post_date).days,
                'matching_skills': resume_data.get('skills', [])[:random.randint(2, 5)] if resume_data.get(
                    'skills') else ['Python', 'JavaScript', 'SQL'][:random.randint(2, 3)],
                'missing_skills': ['Kubernetes', 'Docker', 'AWS', 'React', 'Node.js', 'TypeScript', 'GraphQL'][
                                  :(random.randint(1, 4))],
                'recommendation': self.generate_job_recommendation(exp_level, job_field),
                'description': self.generate_job_description(job_field, exp_level, company),
                'requirements': self.generate_job_requirements(job_field, exp_level),
                'benefits': self.generate_job_benefits(company)
            }
            mock_jobs.append(job)

        return mock_jobs

    def generate_job_recommendation(self, exp_level: str, job_field: str) -> str:
        """Generate contextual job recommendations"""
        recommendations = {
            'entry': [
                f'Perfect entry-level opportunity to start your {job_field} career',
                f'Great company culture for new {job_field} graduates',
                f'Excellent mentorship program for junior {job_field} roles'
            ],
            'junior': [
                f'Good match for your early-career {job_field} experience',
                f'Opportunity to grow your {job_field} skills in a supportive environment',
                f'Strong team collaboration focus perfect for junior developers'
            ],
            'mid': [
                f'Excellent match for your {job_field} experience level',
                f'Great opportunity to take on more technical leadership',
                f'Perfect role to expand your {job_field} expertise'
            ],
            'senior': [
                f'High-impact {job_field} role with significant technical influence',
                f'Leadership opportunity in cutting-edge {job_field} projects',
                f'Excellent compensation and senior-level responsibilities'
            ],
            'executive': [
                f'Executive-level {job_field} position with strategic impact',
                f'Leadership role shaping the future of {job_field} at scale',
                f'High-visibility position with significant decision-making authority'
            ]
        }
        return random.choice(recommendations.get(exp_level, recommendations['mid']))

    def generate_job_description(self, job_field: str, exp_level: str, company: str) -> str:
        """Generate realistic job descriptions"""
        base_desc = f"Join {company}'s {job_field} team and help build the next generation of technology solutions. "

        level_specific = {
            'entry': "We're looking for a motivated new graduate to join our team and learn from experienced engineers.",
            'junior': "We're seeking a developer with 1-3 years of experience to contribute to our growing platform.",
            'mid': "We need an experienced engineer to take ownership of key features and mentor junior team members.",
            'senior': "We're looking for a senior engineer to lead technical initiatives and drive architectural decisions.",
            'executive': "We need a technical leader to shape our engineering strategy and build world-class teams."
        }

        return base_desc + level_specific.get(exp_level, level_specific['mid'])

    def generate_job_requirements(self, job_field: str, exp_level: str) -> list:
        """Generate realistic job requirements"""
        base_requirements = {
            'Software Engineer': ['Programming experience', 'Computer Science degree or equivalent',
                                  'Problem-solving skills'],
            'Data Scientist': ['Statistics/ML knowledge', 'Python/R experience', 'Data analysis skills'],
            'Data Engineer': ['ETL experience', 'SQL proficiency', 'Data pipeline knowledge'],
            'DevOps Engineer': ['Cloud platforms', 'CI/CD experience', 'Infrastructure as code'],
            'Full Stack Developer': ['Frontend & backend development', 'Database knowledge', 'API development']
        }

        requirements = base_requirements.get(job_field, base_requirements['Software Engineer']).copy()

        exp_requirements = {
            'entry': ['0-1 years experience', 'Strong fundamentals', 'Eagerness to learn'],
            'junior': ['1-3 years experience', 'Production code experience', 'Collaboration skills'],
            'mid': ['3-5 years experience', 'System design knowledge', 'Mentoring experience'],
            'senior': ['5+ years experience', 'Technical leadership', 'Architecture experience'],
            'executive': ['10+ years experience', 'Team management', 'Strategic planning']
        }

        requirements.extend(exp_requirements.get(exp_level, exp_requirements['mid']))
        return requirements

    def generate_job_benefits(self, company: str) -> list:
        """Generate realistic job benefits"""
        common_benefits = [
            'Competitive salary and equity',
            'Comprehensive health insurance',
            'Flexible working hours',
            'Professional development budget',
            'Remote work options'
        ]

        company_specific = {
            'Google': ['Free meals', 'On-site gym', '20% time for personal projects'],
            'Meta': ['Wellness programs', 'Parental leave', 'Transportation benefits'],
            'Netflix': ['Unlimited PTO', 'Performance bonuses', 'Learning stipend'],
            'Stripe': ['Home office setup', 'Annual company retreat', 'Stock options']
        }


        benefits = common_benefits.copy()
        if company in company_specific:
            benefits.extend(company_specific[company])
        else:
            benefits.extend(['Annual bonus', 'Stock options', 'Team events'])

        return benefits

    def match_jobs_to_resume(self, jobs: list, resume_data: dict) -> list:
        """Match jobs to resume and return sorted results"""
        matched_jobs = []
        resume_skills = resume_data.get('skills', [])
        resume_keywords = [k.get('word', k) if isinstance(k, dict) else k
                           for k in resume_data.get('keywords', [])]

        for job in jobs:
            # Simple matching logic
            match_score = self.calculate_simple_match_score(job, resume_skills, resume_keywords)

            job_dict = {
                'id': job.get('id', f'job_{hash(job.get("title", ""))}'),
                'title': job.get('title', 'Software Engineer'),
                'company': job.get('company', 'TechCorp'),
                'location': job.get('location', 'Remote'),
                'url': job.get('url', 'https://example.com'),
                'department': job.get('department', 'Engineering'),
                'experience_level': job.get('experience_level', 'mid'),
                'job_type': job.get('job_type', 'Full-time'),
                'remote_type': job.get('remote_type',
                                       'Remote' if 'remote' in job.get('location', '').lower() else 'On-site'),
                'ats_type': job.get('ats_type', 'unknown'),
                'match_score': match_score,
                'matching_skills': [skill for skill in resume_skills[:3] if
                                    skill.lower() in job.get('title', '').lower()],
                'missing_skills': ['Docker', 'Kubernetes', 'AWS'][:2],  # Mock missing skills
                'recommendation': f"{'Excellent' if match_score >= 80 else 'Good'} match for your skills"
            }
            matched_jobs.append(job_dict)

        # Sort by match score
        matched_jobs.sort(key=lambda x: x['match_score'], reverse=True)
        return matched_jobs

    def calculate_simple_match_score(self, job: dict, resume_skills: list, resume_keywords: list) -> int:
        """Calculate a simple match score"""
        score = 60  # Base score
        job_text = f"{job.get('title', '')} {job.get('department', '')}".lower()

        # Skill matching
        matching_skills = [skill for skill in resume_skills if skill.lower() in job_text]
        score += len(matching_skills) * 5

        # Keyword matching
        matching_keywords = [keyword for keyword in resume_keywords if keyword.lower() in job_text]
        score += len(matching_keywords) * 3

        # Add some randomness for variety
        score += random.randint(-10, 15)

        # Cap at 100
        return min(score, 100)


class FastJobRecommendationService:
    """Fast job recommendation service"""

    def __init__(self):
        self.scraper = FastATSJobScraper()

    async def get_jobs_fast(self, job_field: str, resume_data: dict,
                            experience_level: str = None,
                            location_type: str = None,
                            max_jobs: int = 200) -> list:
        """Get jobs quickly with filtering options"""

        # Check cache first
        cached_jobs = self.scraper.cache.get_cached_jobs(job_field)
        if cached_jobs:
            logger.info(f"Using cached jobs for {job_field}")
            jobs = cached_jobs
        else:
            # Generate some realistic mock jobs for now
            logger.info(f"Generating fresh jobs for {job_field}")
            mock_jobs = self.scraper.generate_mock_jobs(job_field, resume_data)

            # Add variety with different companies and experience levels
            additional_jobs = []
            for i in range(6):  # Add 6 more jobs
                additional_jobs.append({
                    'title': f'{job_field} {"Specialist" if i % 2 == 0 else "Expert"}',
                    'company': f'{"Tech" if i % 3 == 0 else "Data" if i % 3 == 1 else "Cloud"}Flow {i}',
                    'location': 'Remote' if i % 2 == 0 else 'San Francisco, CA',
                    'department': 'Engineering',
                    'experience_level': 'senior' if i % 2 == 0 else 'mid',
                    'ats_type': 'lever' if i % 2 == 0 else 'greenhouse'
                })

            jobs = mock_jobs + self.scraper.match_jobs_to_resume(additional_jobs, resume_data)

            # Cache the results
            self.scraper.cache.cache_jobs(jobs, job_field)

        # Apply filters
        filtered_jobs = jobs

        if experience_level:
            filtered_jobs = [job for job in filtered_jobs if job.get('experience_level') == experience_level]

        if location_type:
            if location_type == "remote":
                filtered_jobs = [job for job in filtered_jobs if "remote" in job.get('location', '').lower()]
            elif location_type == "onsite":
                filtered_jobs = [job for job in filtered_jobs if "remote" not in job.get('location', '').lower()]

        return filtered_jobs[:max_jobs]


# Synchronous wrapper for Flask integration
def get_jobs_sync(job_field: str, resume_data: dict, **kwargs) -> list:
    """Synchronous wrapper for async job fetching"""
    try:
        # Create a simple synchronous version
        service = FastJobRecommendationService()
        scraper = service.scraper

        # Generate mock jobs for testing
        logger.info(f"Getting jobs for {job_field}")

        # Create varied mock jobs
        base_jobs = [
            {
                'title': f'Senior {job_field}',
                'company': 'Google',
                'location': 'Mountain View, CA',
                'url': 'https://careers.google.com/jobs/results/123',
                'department': 'Engineering',
                'experience_level': 'senior',
                'ats_type': 'google'
            },
            {
                'title': f'{job_field} - Remote',
                'company': 'Stripe',
                'location': 'Remote',
                'url': 'https://stripe.com/jobs/listing/456',
                'department': 'Engineering',
                'experience_level': 'mid',
                'ats_type': 'greenhouse'
            },
            {
                'title': f'Lead {job_field}',
                'company': 'Databricks',
                'location': 'San Francisco, CA',
                'url': 'https://databricks.com/company/careers/789',
                'department': 'Product Engineering',
                'experience_level': 'senior',
                'ats_type': 'lever'
            },
            {
                'title': f'Junior {job_field}',
                'company': 'Airbnb',
                'location': 'Remote',
                'url': 'https://careers.airbnb.com/positions/101',
                'department': 'Engineering',
                'experience_level': 'junior',
                'ats_type': 'workday'
            },
            {
                'title': f'{job_field} Intern',
                'company': 'Meta',
                'location': 'Menlo Park, CA',
                'url': 'https://www.metacareers.com/jobs/111',
                'department': 'AI Research',
                'experience_level': 'entry',
                'ats_type': 'meta'
            },
            {
                'title': f'Principal {job_field}',
                'company': 'Amazon',
                'location': 'Seattle, WA',
                'url': 'https://amazon.jobs/en/jobs/222',
                'department': 'AWS',
                'experience_level': 'senior',
                'ats_type': 'amazon'
            }
        ]

        # Filter jobs that match the field
        relevant_jobs = [job for job in base_jobs if scraper.is_relevant_job(job['title'], job_field)]

        # If no relevant jobs, use all jobs but modify titles
        if not relevant_jobs:
            relevant_jobs = base_jobs
            for job in relevant_jobs:
                job['title'] = f'{job_field} Engineer' if 'Engineer' not in job_field else job['title'].replace(
                    'Software Engineer', job_field)

        # Match jobs to resume
        matched_jobs = scraper.match_jobs_to_resume(relevant_jobs, resume_data)

        # Apply filters
        experience_level = kwargs.get('experience_level')
        location_type = kwargs.get('location_type')
        max_jobs = kwargs.get('max_jobs', 50)

        if experience_level:
            matched_jobs = [job for job in matched_jobs if job.get('experience_level') == experience_level]

        if location_type == 'remote':
            matched_jobs = [job for job in matched_jobs if 'remote' in job.get('location', '').lower()]
        elif location_type == 'onsite':
            matched_jobs = [job for job in matched_jobs if 'remote' not in job.get('location', '').lower()]

        logger.info(f"Returning {len(matched_jobs)} jobs for {job_field}")
        return matched_jobs[:max_jobs]

    except Exception as e:
        logger.error(f"Error in sync job fetching: {e}")
        return []