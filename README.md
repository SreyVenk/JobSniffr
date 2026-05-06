# JobSniffr

A full-stack web application that analyzes resumes, scrapes real job listings, ranks job matches, and provides skill gap insights using local LLMs.

This project is designed to simulate a production-style system rather than a demo app, with authentication, persistent storage, and an extensible architecture for AI-powered analysis.

---

## Overview

This platform allows users to:

- Upload and parse resumes (PDF, DOCX, TXT)
- Extract structured data including skills, experience, and keywords
- Retrieve real job listings from company career pages (ATS scraping)
- Rank jobs based on relevance to the resume
- Identify missing skills and generate improvement suggestions
- Track saved job applications with persistent storage
- Authenticate using Google OAuth

The system is designed to reflect real-world backend patterns, including API design, database modeling, and modular services.

---

## Tech Stack

**Backend**
- Flask
- SQLAlchemy
- PostgreSQL (Supabase in production)
- Gunicorn

**Frontend**
- HTML / CSS / JavaScript (server-rendered templates)

**Data & Processing**
- Resume parsing with PyPDF2 and python-docx
- Web scraping with BeautifulSoup
- Matching and scoring engine (custom logic)

**AI Integration**
- Local LLM inference via Ollama (Mistral / LLaMA)
- Rule-based fallback when LLM is unavailable

**Infrastructure**
- Render (backend hosting)
- Supabase (PostgreSQL database)

---

## Architecture

The application follows a modular structure:

- `app.py` — application factory, routes, and API layer
- `enhanced_ats_scraper.py` — job scraping, matching, and AI analysis
- `models` (SQLAlchemy) — User, Resume, Application
- `ResumeParser` — structured data extraction from resumes
- `JobRecommendationService` — job retrieval, filtering, and ranking
- `OllamaClient` — local LLM interface for skill gap analysis

Key system behaviors:

- Resume parsing and job matching are handled independently
- Job scraping runs per request and is cached in-memory
- AI analysis is optional but integrated into the core pipeline
- Application tracking persists data in the database (no localStorage)

---

## Features

### Resume Parsing
- Extracts:
  - Contact information
  - Skills
  - Experience
  - Education
  - Keywords
- Supports PDF, DOCX, and TXT formats

### Job Scraping
- Pulls listings from real company career pages
- Filters by relevance to job field
- Deduplicates and normalizes results

### Matching Engine
- Scores jobs based on:
  - Skill overlap
  - Keyword relevance
  - Title alignment
- Returns:
  - Match score (0–100)
  - Matching skills
  - Missing skills
  - Recommendation summary

### Skill Gap Analysis
- Uses local LLM (via Ollama) when available
- Generates:
  - Fit assessment
  - Missing skills
  - Resume improvement suggestions
  - Interview talking points
- Falls back to rule-based analysis if LLM is unavailable

### Application Tracking
- Save jobs to database
- Update application status
- Retrieve user-specific application history

### Authentication
- Google OAuth login
- Session-based authentication (Flask-Login)

---

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd <repo-name>
