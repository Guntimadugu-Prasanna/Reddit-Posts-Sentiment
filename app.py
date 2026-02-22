from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import re
import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

app = Flask(__name__)

# Allow all origins (safe for development)
CORS(app)
# -----------------------------
# App Configuration
# -----------------------------
DATABASE = "instances/analysis.db"


# ------------------------------
# Sentiment Word Lists
# ------------------------------

POSITIVE_WORDS = {
    "good", "great", "awesome", "excellent", "love", "amazing",
    "fantastic", "wonderful", "best", "nice", "super",
    "perfect", "happy", "glad"
}

NEGATIVE_WORDS = {
    "bad", "terrible", "awful", "hate", "worst", "poor",
    "sucks", "horrible", "disappointing", "dislike",
    "stupid", "useless", "waste", "annoying"
}

# ------------------------------
# Sentiment Analyzer
# ------------------------------

def analyze_sentiment(text):
    text = text.lower()
    pos = sum(1 for word in POSITIVE_WORDS if word in text)
    neg = sum(1 for word in NEGATIVE_WORDS if word in text)

    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"

# ------------------------------
# Reddit Helpers
# ------------------------------

def extract_post_id(url):
    s = url.split('/comments/')
    uid = s[1].split('/')[0] if '/' in s[1] else s[1]
    print("Extracted post ID:", uid)
    return uid
    match = re.search(r"/comments/([a-zA-Z0-9]+)/", url)
    return match.group(1) if match else None


def extract_comments(node, comments):
    if node.get("kind") == "t1":
        body = node["data"].get("body", "")
        if body.strip():
            comments.append(body)

        replies = node["data"].get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            for child in children:
                extract_comments(child, comments)


def fetch_comments(post_id):
    url = f"https://www.reddit.com/comments/{post_id}.json"
    headers = {"User-Agent": "Reddit Sentiment Analyzer by /u/me"}

    print(f"Fetching comments from Reddit for post ID: {post_id}")

    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        raise Exception("Failed to fetch Reddit data")

    data = response.json()
    comments = []

    if isinstance(data, list) and len(data) > 1:
        children = data[1]["data"]["children"]
        for child in children:
            extract_comments(child, comments)

    return comments


@app.route("/")
def home():
    return render_template("index.html")

# ------------------------------
# API Route (Matches Your Frontend)
# ------------------------------

@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()

        if not data or "url" not in data:
            return jsonify({"error": "URL is required"}), 400

        url = data["url"].strip()

        if not url:
            return jsonify({"error": "URL cannot be empty"}), 400

        post_id = extract_post_id(url)

        if not post_id:
            return jsonify({"error": "Invalid Reddit URL"}), 400

        comments = fetch_comments(post_id)

        positive = negative = neutral = 0

        for comment in comments:
            sentiment = analyze_sentiment(comment)
            if sentiment == "positive":
                positive += 1
            elif sentiment == "negative":
                negative += 1
            else:
                neutral += 1

        return jsonify({
            "positive": positive,
            "negative": negative,
            "neutral": neutral
        }), 200

    except Exception as e:
        print("Backend error:", e)
        return jsonify({"error": "Analysis failed"}), 500


# -----------------------------
# Database Helper
# -----------------------------

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs("instances", exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# Initialize database on startup
init_db()

# -----------------------------
# Signup Route
# -----------------------------

@app.route("/signup", methods=["POST"])
def signup():
    try:
        data = request.get_json()

        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        if not username or not email or not password:
            return jsonify({"error": "All fields are required"}), 400

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, hashed_password),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "User already exists"}), 409
        finally:
            conn.close()

        return jsonify({"message": "User created successfully"}), 201

    except Exception as e:
        return jsonify({"error": "Signup failed"}), 500


# -----------------------------
# Login Route
# -----------------------------

@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()

        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        if not email or not password:
            return jsonify({"error": "Email and password are required"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if not user or not check_password_hash(user["password"], password):
            return jsonify({"error": "Invalid credentials"}), 401

        token = jwt.encode(
            {
                "user_id": user["id"],
                "email": user["email"],
                "exp": datetime.utcnow() + timedelta(hours=24),
            },
            app.config["SECRET_KEY"] or "sentiment-analyzer-secret",
            algorithm="HS256",
        )

        return jsonify({"token": token}), 200

    except Exception as e:
        print("Login error:", e)
        return jsonify({"error": "Login failed"}), 500


# -----------------------------
# Run App
# -----------------------------

if __name__ == "__main__":
    app.run(debug=True)