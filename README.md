# Synapy - The Gamified Cognitive Assessment Platform

Synapy is a B2C cognitive assessment and problem-solving platform designed for individual consumers. Think of it like LeetCode, but applied to a wider array of industries, using short, engaging, game-styled puzzles. 

By evaluating users' core cognitive fitness—working memory, processing speed, spatial reasoning, and pattern recognition—Synapy allows individuals to train and showcase their talents across various domains without the stress of traditional tests.

## Core Features & Free/Paid Tiers
- **Gamified Assessments:** Users play varied, short, and engaging game-like puzzles tailored to specific industries (e.g., Software Engineering, Logistics, Customer Success).
- **Deep Performance Metrics:** Instead of pass/fail, Synapy tracks granular performance metrics (completion time, error rates, efficiency) to place users into percentiles.
- **Three Access Tiers:**
  - *Unregistered Free:* General challenges.
  - *Registered Free:* General + Daily Random + Limited Career Puzzles + "g-factor" dashboard.
  - *Paid Premium:* Full Career Puzzles + Domain-specific statistical dashboard.
- **Aesthetic philosophy:** A precise 3:2 ratio of "Professional : Gamified" UI/UX.

## For Developers & AI Agents 🤖

When working on this codebase, **always read these documents first** to understand the architecture and design philosophy:
- `CLAUDE.md`: Contains the overall project vision, technology stack, and standard commands.
- `docs/PUZZLE_DESIGN.md`: Rules for how assessment games should mechanics, data tracking, and aesthetics.

## Tech Stack
- **Backend:** Flask (Python)
- **Database:** SQLite & SQLAlchemy
- **Frontend structure:** HTML/Vanilla JS/CSS logic within Jinja templates

## Quickstart

```bash
# 1. Activate virtual environment (Windows)
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed the database with initial game types
python seed.py

# 4. Run the Flask development server
python app.py
```

Then visit `http://127.0.0.1:5000` in your browser.
