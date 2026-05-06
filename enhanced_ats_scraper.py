import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import ollama

    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False


@dataclass
class JobListing:
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    department: str = ""
    experience_level: str = "mid"
    job_type: str = "Full-time"
    remote_type: str = "Not specified"
    salary_range: str = ""
    posted_date: str = ""
    required_skills: Optional[List[str]] = None
    ats_type: str = "unknown"
    source: str = "scraped"

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "description": self.description,
            "department": self.department,
            "experience_level": self.experience_level,
            "job_type": self.job_type,
            "remote_type": self.remote_type,
            "salary_range": self.salary_range,
            "posted_date": self.posted_date,
            "required_skills": self.required_skills or [],
            "ats_type": self.ats_type,
            "source": self.source,
        }


class JobCache:
    def __init__(self, ttl_seconds=3600):
        self.ttl_seconds = ttl_seconds
        self.cache = {}

    def _key(self, params):
        serialized = json.dumps(params, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, params):
        key = self._key(params)
        cached = self.cache.get(key)

        if not cached:
            return None

        value, created_at = cached

        if time.time() - created_at > self.ttl_seconds:
            self.cache.pop(key, None)
            return None

        return value

    def set(self, params, value):
        key = self._key(params)
        self.cache[key] = (value, time.time())


class OllamaClient:
    def __init__(self):
        self.enabled = OLLAMA_AVAILABLE
        self.model = os.getenv("OLLAMA_MODEL", "mistral")
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.client = None

        if not self.enabled:
            return

        try:
            self.client = ollama.Client(host=self.host)
            logger.info("Ollama initialized with model=%s host=%s", self.model, self.host)
        except Exception as exc:
            logger.warning("Ollama failed to initialize: %s", exc)
            self.enabled = False

    def generate(self, prompt, max_chars=1200):
        if not self.enabled or not self.client:
            return None

        try:
            response = self.client.generate(model=self.model, prompt=prompt)
            text = response.get("response", "").strip()
            return text[:max_chars]
        except Exception as exc:
            logger.warning("Ollama generation failed: %s", exc)
            return None


class RealJobScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                )
            }
        )

        self.companies = [
            {
                "name": "Stripe",
                "url": "https://stripe.com/jobs/search",
                "ats_type": "custom",
            },
            {
                "name": "Vercel",
                "url": "https://vercel.com/careers",
                "ats_type": "custom",
            },
            {
                "name": "Figma",
                "url": "https://www.figma.com/careers/",
                "ats_type": "custom",
            },
            {
                "name": "Notion",
                "url": "https://www.notion.so/careers",
                "ats_type": "custom",
            },
            {
                "name": "Linear",
                "url": "https://linear.app/careers",
                "ats_type": "custom",
            },
            {
                "name": "GitLab",
                "url": "https://about.gitlab.com/jobs/all-jobs/",
                "ats_type": "custom",
            },
            {
                "name": "Mozilla",
                "url": "https://www.mozilla.org/en-US/careers/listings/",
                "ats_type": "custom",
            },
        ]

        self.field_keywords = {
            "software engineer": [
                "software",
                "engineer",
                "developer",
                "backend",
                "frontend",
                "full stack",
                "full-stack",
                "platform",
            ],
            "backend engineer": [
                "backend",
                "api",
                "platform",
                "software engineer",
                "server",
                "distributed",
            ],
            "data engineer": [
                "data engineer",
                "pipeline",
                "etl",
                "data platform",
                "analytics engineer",
            ],
            "devops engineer": [
                "devops",
                "sre",
                "site reliability",
                "infrastructure",
                "platform engineer",
                "cloud",
            ],
            "ai application engineer": [
                "ai",
                "machine learning",
                "ml",
                "llm",
                "applied ai",
                "nlp",
            ],
        }

    def scrape_all_companies(self, job_field, max_jobs=50):
        jobs = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.scrape_company_jobs, company, job_field)
                for company in self.companies
            ]

            for future in as_completed(futures):
                try:
                    jobs.extend(future.result())
                except Exception as exc:
                    logger.warning("Company scrape failed: %s", exc)

                if len(jobs) >= max_jobs:
                    break

        return jobs[:max_jobs]

    def scrape_company_jobs(self, company, job_field):
        logger.info("Scraping %s for %s", company["name"], job_field)

        try:
            response = self.session.get(company["url"], timeout=15)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", company["name"], exc)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a", href=True)

        jobs = []

        for link in links:
            title = " ".join(link.get_text(" ", strip=True).split())
            href = link.get("href")

            if not title or not href:
                continue

            absolute_url = urljoin(company["url"], href)

            if not self.looks_like_job_url(absolute_url, title):
                continue

            if not self.is_relevant(title, job_field):
                continue

            job = JobListing(
                id=self.make_job_id(company["name"], absolute_url),
                title=title[:180],
                company=company["name"],
                location=self.extract_location(link) or "Not specified",
                url=absolute_url,
                department=self.extract_department(title),
                experience_level=self.extract_experience_level(title),
                remote_type=self.extract_remote_type(title),
                ats_type=company.get("ats_type", "custom"),
                posted_date=datetime.utcnow().strftime("%Y-%m-%d"),
                source="scraped",
            )

            if not any(existing.url == job.url for existing in jobs):
                jobs.append(job)

            if len(jobs) >= 12:
                break

        return jobs

    def looks_like_job_url(self, url, title):
        combined = f"{url} {title}".lower()
        bad_terms = ["privacy", "terms", "cookie", "blog", "press", "news", "help"]
        good_terms = ["job", "career", "position", "opening", "engineer", "developer"]

        if any(term in combined for term in bad_terms):
            return False

        return any(term in combined for term in good_terms)

    def is_relevant(self, title, job_field):
        title_lower = title.lower()
        keywords = self.field_keywords.get(job_field.lower(), job_field.lower().split())

        return any(keyword in title_lower for keyword in keywords)

    def extract_location(self, link):
        parent_text = ""

        try:
            parent = link.parent
            if parent:
                parent_text = parent.get_text(" ", strip=True)
        except Exception:
            pass

        patterns = [
            r"\bRemote\b",
            r"\bHybrid\b",
            r"\bNew York\b",
            r"\bSan Francisco\b",
            r"\bSeattle\b",
            r"\bAustin\b",
            r"\bBoston\b",
            r"\bChicago\b",
            r"\bLos Angeles\b",
            r"\bUnited States\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, parent_text, re.IGNORECASE)
            if match:
                return match.group(0)

        return None

    def extract_experience_level(self, title):
        title_lower = title.lower()

        if any(term in title_lower for term in ["intern", "new grad", "entry"]):
            return "entry"
        if any(term in title_lower for term in ["junior", "associate"]):
            return "junior"
        if any(term in title_lower for term in ["senior", "sr.", "lead", "staff", "principal"]):
            return "senior"

        return "mid"

    def extract_remote_type(self, title):
        title_lower = title.lower()

        if "remote" in title_lower:
            return "Remote"
        if "hybrid" in title_lower:
            return "Hybrid"

        return "Not specified"

    def extract_department(self, title):
        title_lower = title.lower()

        if "data" in title_lower:
            return "Data"
        if "security" in title_lower:
            return "Security"
        if "platform" in title_lower:
            return "Platform"
        if "frontend" in title_lower:
            return "Frontend"
        if "backend" in title_lower:
            return "Backend"

        return "Engineering"

    def make_job_id(self, company, url):
        raw = f"{company}:{url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class JobMatcher:
    def __init__(self):
        self.skill_aliases = {
            "javascript": ["javascript", "js", "node", "node.js", "react"],
            "typescript": ["typescript", "ts"],
            "python": ["python", "flask", "fastapi", "django"],
            "java": ["java", "spring"],
            "sql": ["sql", "postgres", "postgresql", "mysql", "sqlite"],
            "aws": ["aws", "lambda", "s3", "api gateway", "dynamodb"],
            "docker": ["docker", "container"],
            "kubernetes": ["kubernetes", "k8s"],
            "redis": ["redis", "cache", "caching"],
            "ai": ["ai", "llm", "ollama", "hugging face", "nlp", "machine learning"],
        }

    def match_jobs(self, jobs, resume_data):
        matched = []

        for job in jobs:
            job_dict = job.to_dict() if isinstance(job, JobListing) else job
            score_data = self.score_job(job_dict, resume_data)

            job_dict.update(score_data)
            matched.append(job_dict)

        matched.sort(key=lambda item: item["match_score"], reverse=True)
        return matched

    def score_job(self, job, resume_data):
        resume_skills = [skill.lower() for skill in resume_data.get("skills", [])]
        resume_keywords = [
            keyword.get("word", keyword).lower()
            if isinstance(keyword, dict)
            else str(keyword).lower()
            for keyword in resume_data.get("keywords", [])
        ]

        job_text = " ".join(
            [
                job.get("title", ""),
                job.get("description", ""),
                job.get("department", ""),
                job.get("company", ""),
            ]
        ).lower()

        matching_skills = []
        missing_skills = []

        normalized_resume_terms = set(resume_skills + resume_keywords)

        for canonical, aliases in self.skill_aliases.items():
            resume_has_skill = any(alias in " ".join(normalized_resume_terms) for alias in aliases)
            job_mentions_skill = any(alias in job_text for alias in aliases)

            if resume_has_skill and job_mentions_skill:
                matching_skills.append(canonical)
            elif job_mentions_skill and not resume_has_skill:
                missing_skills.append(canonical)

        title_bonus = self.title_relevance_bonus(job.get("title", ""))
        skill_score = min(len(matching_skills) * 12, 60)
        keyword_score = min(
            len([keyword for keyword in resume_keywords if keyword in job_text]) * 5,
            20,
        )

        score = 20 + skill_score + keyword_score + title_bonus - min(len(missing_skills) * 3, 15)
        score = max(0, min(score, 100))

        return {
            "match_score": score,
            "matching_skills": sorted(set(matching_skills)),
            "missing_skills": sorted(set(missing_skills))[:8],
            "recommendation": self.basic_recommendation(score, matching_skills, missing_skills),
        }

    def title_relevance_bonus(self, title):
        title_lower = title.lower()

        if any(term in title_lower for term in ["software", "backend", "platform", "developer"]):
            return 15
        if any(term in title_lower for term in ["data", "devops", "sre", "cloud"]):
            return 10

        return 0

    def basic_recommendation(self, score, matching_skills, missing_skills):
        if score >= 80:
            return "Strong match. Prioritize this role and tailor bullets around the matching skills."
        if score >= 60:
            return "Moderate match. Apply if the company is strong, but address missing skills in the resume."
        if missing_skills:
            return f"Weak-to-moderate match. Biggest gaps: {', '.join(missing_skills[:3])}."

        return "Low match based on available job text."


class JobRecommendationService:
    def __init__(self):
        self.cache = JobCache()
        self.scraper = RealJobScraper()
        self.matcher = JobMatcher()
        self.ollama_client = OllamaClient()
        self.enable_demo_jobs = os.getenv("ENABLE_DEMO_JOBS", "false").lower() == "true"

    def get_jobs(self, job_field, resume_data, experience_level=None, location_type=None, max_jobs=50):
        params = {
            "job_field": job_field,
            "resume_skills": resume_data.get("skills", []),
            "experience_level": experience_level,
            "location_type": location_type,
            "max_jobs": max_jobs,
            "demo": self.enable_demo_jobs,
        }

        cached = self.cache.get(params)
        if cached:
            return cached

        jobs = self.scraper.scrape_all_companies(job_field, max_jobs=max_jobs)

        if self.enable_demo_jobs and len(jobs) < max_jobs:
            jobs.extend(self.generate_demo_jobs(job_field, max_jobs - len(jobs)))

        matched_jobs = self.matcher.match_jobs(jobs, resume_data)
        filtered_jobs = self.apply_filters(matched_jobs, experience_level, location_type)
        final_jobs = filtered_jobs[:max_jobs]

        self.cache.set(params, final_jobs)
        return final_jobs

    def apply_filters(self, jobs, experience_level=None, location_type=None):
        filtered = jobs

        if experience_level:
            filtered = [
                job for job in filtered if job.get("experience_level") == experience_level
            ]

        if location_type:
            location_type_lower = location_type.lower()

            if location_type_lower == "remote":
                filtered = [
                    job
                    for job in filtered
                    if "remote" in job.get("location", "").lower()
                    or "remote" in job.get("remote_type", "").lower()
                ]
            elif location_type_lower == "hybrid":
                filtered = [
                    job
                    for job in filtered
                    if "hybrid" in job.get("location", "").lower()
                    or "hybrid" in job.get("remote_type", "").lower()
                ]
            elif location_type_lower == "onsite":
                filtered = [
                    job
                    for job in filtered
                    if "remote" not in job.get("location", "").lower()
                    and "remote" not in job.get("remote_type", "").lower()
                ]

        return filtered

    def generate_demo_jobs(self, job_field, count):
        demo_jobs = []

        for index in range(count):
            title = f"{job_field} Demo Role {index + 1}"
            company = f"Demo Company {index + 1}"

            demo_jobs.append(
                JobListing(
                    id=f"demo_{index}",
                    title=title,
                    company=company,
                    location="Remote",
                    url="https://example.com",
                    description=(
                        "Demo job used only when ENABLE_DEMO_JOBS=true. "
                        "Requires Python, SQL, APIs, Docker, and cloud experience."
                    ),
                    department="Engineering",
                    experience_level="junior" if index % 2 == 0 else "mid",
                    remote_type="Remote",
                    ats_type="demo",
                    source="demo",
                )
            )

        return demo_jobs


def get_jobs_sync(job_field, resume_data, **kwargs):
    service = JobRecommendationService()

    return service.get_jobs(
        job_field=job_field,
        resume_data=resume_data,
        experience_level=kwargs.get("experience_level"),
        location_type=kwargs.get("location_type"),
        max_jobs=int(kwargs.get("max_jobs", 50)),
    )


def get_skill_gap_analysis(resume_data, job_description):
    ollama_client = OllamaClient()

    resume_skills = resume_data.get("skills", [])
    resume_experience = resume_data.get("experience", [])
    resume_keywords = resume_data.get("keywords", [])

    prompt = f"""
You are an engineering hiring reviewer.

Analyze this candidate against the job description.

Return a concise structured review with:
1. Overall fit: strong/moderate/weak
2. Matching skills
3. Missing skills
4. Resume bullet improvements
5. Interview talking points
6. Final recommendation

Candidate skills:
{resume_skills}

Candidate experience:
{resume_experience}

Candidate keywords:
{resume_keywords}

Job description:
{job_description}
"""

    ai_response = ollama_client.generate(prompt)

    if ai_response:
        return {
            "success": True,
            "engine": "ollama",
            "model": ollama_client.model,
            "analysis": ai_response,
        }

    fallback = fallback_skill_gap(resume_data, job_description)

    return {
        "success": True,
        "engine": "rule-based-fallback",
        "model": None,
        "analysis": fallback,
    }


def fallback_skill_gap(resume_data, job_description):
    resume_skills = {skill.lower() for skill in resume_data.get("skills", [])}
    job_text = job_description.lower()

    common_skills = [
        "python",
        "java",
        "javascript",
        "typescript",
        "react",
        "node",
        "sql",
        "postgresql",
        "aws",
        "docker",
        "kubernetes",
        "redis",
        "api",
        "flask",
        "fastapi",
        "linux",
    ]

    matching = sorted([skill for skill in common_skills if skill in resume_skills and skill in job_text])
    missing = sorted([skill for skill in common_skills if skill not in resume_skills and skill in job_text])

    return {
        "overall_fit": "moderate" if len(matching) >= 3 else "weak",
        "matching_skills": matching,
        "missing_skills": missing,
        "resume_bullet_improvements": [
            "Add quantified impact to backend/API work.",
            "Mention deployed services, database usage, and production-style debugging.",
            "Tie project bullets directly to job keywords.",
        ],
        "interview_talking_points": [
            "Explain the resume parsing pipeline.",
            "Explain the scraping and matching system.",
            "Discuss what you would scale with Postgres, Redis, queues, and background workers.",
        ],
    }