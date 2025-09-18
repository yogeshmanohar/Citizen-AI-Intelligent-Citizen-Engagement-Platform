"""
Citizen AI - Intelligent Citizen Engagement Platform
Single-file Flask app example (prototype)

Features:
- Submit citizen feedback (title, text, category, contact)
- View/list feedback
- Simple keyword-based theme tagging
- Simple rule-based sentiment scoring
- Summarize recurring themes and generate short insights
- Stores data in SQLite (persistent file: citizen_ai.db)

Notes:
- This is a prototype to demonstrate structure and logic. For production use, replace rule-based NLP with
  robust libraries (spaCy, transformers) and add authentication, rate-limiting, input validation, and tests.
- To run: pip install flask
  then: python citizen_ai.py

"""

from flask import Flask, request, jsonify, g
import sqlite3
import re
from collections import Counter, defaultdict
from datetime import datetime

DB_PATH = 'citizen_ai.db'

app = Flask(__name__)

# ----------------------------
# Database helpers
# ----------------------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            body TEXT,
            category TEXT,
            contact TEXT,
            tags TEXT,
            sentiment REAL,
            created_at TEXT
        )
    ''')
    db.commit()


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ----------------------------
# Simple NLP helpers (rule-based)
# ----------------------------

POSITIVE_WORDS = set(["good","great","excellent","happy","satisfied","love","like","awesome","fast","helpful","resolved","thank"])
NEGATIVE_WORDS = set(["bad","poor","terrible","angry","disappointed","hate","slow","delay","delayed","not","issue","problem","complaint","refund","frustrat"])

THEME_KEYWORDS = {
    'refunds': ['refund', 'refunds', 'reimbursement'],
    'delivery': ['delivery','deliver','shipping','shipment','ship','delay','delayed'],
    'service': ['service','support','helpdesk','customer service','agent'],
    'infrastructure': ['road','water','electric','power','sewage','street','lighting'],
    'safety': ['safety','crime','police','accident','danger'],
    'education': ['school','college','education','teacher','exam']
}

WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text):
    return [w.lower() for w in WORD_RE.findall(text)]


def simple_sentiment_score(text):
    """Return a score between -1 (negative) and +1 (positive)"""
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    pos = sum(1 for t in tokens if any(t.startswith(p) for p in POSITIVE_WORDS))
    neg = sum(1 for t in tokens if any(t.startswith(n) for n in NEGATIVE_WORDS))
    score = (pos - neg) / max(1, (pos + neg))
    # normalize to -1..1
    if score > 1: score = 1
    if score < -1: score = -1
    return round(score, 3)


def tag_themes(text):
    tokens = tokenize(text)
    tags = set()
    for theme, kws in THEME_KEYWORDS.items():
        for kw in kws:
            if any(kw in t for t in tokens):
                tags.add(theme)
                break
    # fallback: common nouns as tag candidates
    return list(tags) if tags else ['general']

# ----------------------------
# API Endpoints
# ----------------------------

@app.route('/init', methods=['POST'])
def api_init():
    """Initialize DB (call once)"""
    init_db()
    return jsonify({'status':'ok','message':'database initialized'})


@app.route('/feedback', methods=['POST'])
def submit_feedback():
    """Submit a citizen feedback entry (JSON)
    Required: title, body
    Optional: category, contact
    """
    data = request.get_json(force=True)
    title = data.get('title','').strip()
    body = data.get('body','').strip()
    category = data.get('category','').strip() or 'uncategorized'
    contact = data.get('contact','').strip()

    if not body and not title:
        return jsonify({'error':'title or body required'}), 400

    sentiment = simple_sentiment_score(title + ' ' + body)
    tags = tag_themes(title + ' ' + body)
    created_at = datetime.utcnow().isoformat()

    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO feedback (title, body, category, contact, tags, sentiment, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                   (title, body, category, contact, ','.join(tags), sentiment, created_at))
    db.commit()
    fid = cursor.lastrowid
    return jsonify({'status':'ok','id':fid, 'sentiment':sentiment, 'tags':tags})


@app.route('/feedback', methods=['GET'])
def list_feedback():
    """List feedback entries with optional filters: ?tag=refunds&min_sent=-0.5"""
    tag = request.args.get('tag')
    min_sent = float(request.args.get('min_sent', '-1'))
    db = get_db()
    cursor = db.cursor()
    rows = cursor.execute('SELECT * FROM feedback ORDER BY created_at DESC').fetchall()
    out = []
    for r in rows:
        tags = r['tags'].split(',') if r['tags'] else []
        if tag and tag not in tags:
            continue
        if r['sentiment'] < min_sent:
            continue
        out.append({
            'id': r['id'], 'title': r['title'], 'body': r['body'], 'category': r['category'],
            'contact': r['contact'], 'tags': tags, 'sentiment': r['sentiment'], 'created_at': r['created_at']
        })
    return jsonify(out)


@app.route('/insights/summary', methods=['GET'])
def summary_insights():
    """Generate a short summary of recurring themes, counts, and average sentiment."""
    db = get_db()
    cursor = db.cursor()
    rows = cursor.execute('SELECT * FROM feedback').fetchall()
    if not rows:
        return jsonify({'summary':'no data'}), 200
    tag_counter = Counter()
    cat_counter = Counter()
    sentiments = defaultdict(list)
    for r in rows:
        tags = r['tags'].split(',') if r['tags'] else ['general']
        for t in tags:
            tag_counter[t] += 1
            sentiments[t].append(r['sentiment'])
        cat_counter[r['category']] += 1

    top_tags = tag_counter.most_common(6)
    insights = []
    for tag, cnt in top_tags:
        avg_sent = round(sum(sentiments[tag]) / max(1, len(sentiments[tag])),3)
        insights.append({'theme':tag, 'count':cnt, 'avg_sentiment':avg_sent})

    overall = {
        'total_feedback': sum(cat_counter.values()),
        'by_category': dict(cat_counter.most_common()),
        'top_themes': insights
    }
    return jsonify(overall)


@app.route('/insights/actionable', methods=['GET'])
def actionable_recommendations():
    """Produce simple actionable suggestions based on negative themes."""
    db = get_db()
    cursor = db.cursor()
    rows = cursor.execute('SELECT * FROM feedback').fetchall()
    tag_sentiments = defaultdict(list)
    for r in rows:
        tags = r['tags'].split(',') if r['tags'] else ['general']
        for t in tags:
            tag_sentiments[t].append(r['sentiment'])
    recs = []
    for tag, svals in tag_sentiments.items():
        avg = sum(svals)/max(1,len(svals))
        if avg < -0.2:
            recs.append({'theme':tag, 'issue':'negative_sentiment', 'suggestion': f"Investigate {tag} complaints; prioritize root-cause analysis and targeted communication."})
    if not recs:
        recs = [{'note':'No strongly negative themes detected. Monitor trends.'}]
    return jsonify({'recommendations': recs})


# ----------------------------
# Simple web UI (optional)
# ----------------------------
@app.route('/')
def home():
    return '''
    <h2>Citizen AI - Intelligent Citizen Engagement (Prototype)</h2>
    <p>Use the /feedback endpoint to POST feedback as JSON, e.g.</p>
    <pre>{"title":"Delivery delay","body":"My package was delayed 5 days","category":"logistics","contact":"user@example.com"}</pre>
    <p>Call <a href="/insights/summary">/insights/summary</a> for a quick summary.</p>
    '''

if __name__ == '__main__':
    # Initialize DB on first run
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
