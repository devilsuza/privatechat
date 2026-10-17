from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import hashlib
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "super_secret_boss_key"
CORS(app)

def get_db_connection():
    conn = sqlite3.connect('chat_users_v2.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # Users table (Phone number added)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, phone TEXT NOT NULL, peer_id TEXT)''')
    # Friends table
    conn.execute('''CREATE TABLE IF NOT EXISTS friends (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, receiver TEXT NOT NULL, status TEXT DEFAULT 'pending')''')
    # Status table (For WhatsApp like status)
    conn.execute('''CREATE TABLE IF NOT EXISTS statuses (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, content TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    # OTP table
    conn.execute('''CREATE TABLE IF NOT EXISTS otps (username TEXT PRIMARY KEY, otp TEXT NOT NULL, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/auth', methods=['POST'])
def auth():
    data = request.json
    action = data.get('action')
    username = data.get('username')
    password = hashlib.sha256(data.get('password').encode()).hexdigest() if data.get('password') else ""
    phone = data.get('phone', '')
    peer_id = data.get('peer_id')
    
    conn = get_db_connection()
    try:
        if action == 'signup':
            conn.execute('INSERT INTO users (username, password, phone, peer_id) VALUES (?, ?, ?, ?)', (username, password, phone, peer_id))
            conn.commit()
            return jsonify({"success": True, "message": "Account created!"})
        elif action == 'login':
            user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
            if user:
                conn.execute('UPDATE users SET peer_id = ? WHERE username = ?', (peer_id, username))
                conn.commit()
                return jsonify({"success": True})
            return jsonify({"success": False, "error": "Invalid credentials!"}), 401
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "Username already exists!"}), 400
    finally:
        conn.close()

@app.route('/update_peer', methods=['POST'])
def update_peer():
    data = request.json
    conn = get_db_connection()
    conn.execute('UPDATE users SET peer_id = ? WHERE username = ?', (data.get('peer_id'), data.get('username')))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/search', methods=['GET'])
def search_user():
    query = request.args.get('username')
    me = request.args.get('me')
    conn = get_db_connection()
    users = conn.execute('SELECT username FROM users WHERE username LIKE ? AND username != ? LIMIT 5', ('%'+query+'%', me)).fetchall()
    conn.close()
    return jsonify([u['username'] for u in users])

@app.route('/friend_action', methods=['POST'])
def friend_action():
    data = request.json
    action = data.get('action')
    sender = data.get('sender')
    receiver = data.get('receiver')
    
    conn = get_db_connection()
    if action == 'send':
        existing = conn.execute('SELECT * FROM friends WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)', (sender, receiver, receiver, sender)).fetchone()
        if not existing:
            conn.execute('INSERT INTO friends (sender, receiver) VALUES (?, ?)', (sender, receiver))
    elif action == 'accept':
        conn.execute("UPDATE friends SET status = 'accepted' WHERE sender = ? AND receiver = ?", (receiver, sender))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/get_dashboard_data', methods=['GET'])
def get_dashboard_data():
    me = request.args.get('username')
    conn = get_db_connection()
    pending = conn.execute("SELECT sender FROM friends WHERE receiver = ? AND status = 'pending'", (me,)).fetchall()
    friends = conn.execute("SELECT sender, receiver FROM friends WHERE status = 'accepted' AND (sender = ? OR receiver = ?)", (me, me)).fetchall()
    
    friend_list = []
    for f in friends:
        friend_name = f['sender'] if f['receiver'] == me else f['receiver']
        peer_data = conn.execute("SELECT peer_id FROM users WHERE username = ?", (friend_name,)).fetchone()
        friend_list.append({"username": friend_name, "peer_id": peer_data['peer_id'] if peer_data else None})
        
    # Get recent statuses from friends
    statuses = conn.execute('''SELECT username, content, timestamp FROM statuses 
                               WHERE username IN (SELECT sender FROM friends WHERE receiver = ? AND status='accepted' 
                               UNION SELECT receiver FROM friends WHERE sender = ? AND status='accepted' UNION SELECT ?)
                               AND timestamp >= datetime('now', '-1 day') ORDER BY timestamp DESC''', (me, me, me)).fetchall()
    
    conn.close()
    return jsonify({
        "requests": [p['sender'] for p in pending], 
        "friends": friend_list,
        "statuses": [{"username": s['username'], "content": s['content']} for s in statuses]
    })

@app.route('/post_status', methods=['POST'])
def post_status():
    data = request.json
    conn = get_db_connection()
    conn.execute('INSERT INTO statuses (username, content) VALUES (?, ?)', (data.get('username'), data.get('content')))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# OTP ROUTES
@app.route('/request_otp', methods=['POST'])
def request_otp():
    data = request.json
    username = data.get('username')
    phone = data.get('phone')
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ? AND phone = ?', (username, phone)).fetchone()
    if user:
        otp = str(random.randint(1000, 9999))
        conn.execute('REPLACE INTO otps (username, otp) VALUES (?, ?)', (username, otp))
        conn.commit()
        conn.close()
        # DEMO: Normally send via SMS API. Here we return it to show in UI alert for testing.
        return jsonify({"success": True, "demo_otp": otp})
    conn.close()
    return jsonify({"success": False, "error": "Invalid Username or Phone number"}), 400

@app.route('/reset_password', methods=['POST'])
def reset_password():
    data = request.json
    username = data.get('username')
    otp = data.get('otp')
    new_pass = hashlib.sha256(data.get('new_password').encode()).hexdigest()
    
    conn = get_db_connection()
    valid_otp = conn.execute('SELECT * FROM otps WHERE username = ? AND otp = ?', (username, otp)).fetchone()
    if valid_otp:
        conn.execute('UPDATE users SET password = ? WHERE username = ?', (new_pass, username))
        conn.execute('DELETE FROM otps WHERE username = ?', (username,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    conn.close()
    return jsonify({"success": False, "error": "Invalid OTP"}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
