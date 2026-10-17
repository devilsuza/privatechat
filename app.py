from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import hashlib
import random
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "super_secret_boss_key"
CORS(app)

# MAGIC TRICK: Render par Postgres chalega, Laptop par SQLite
db_url = os.environ.get('DATABASE_URL', 'sqlite:///chat_users_v3.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database Tables Design
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    peer_id = db.Column(db.String(120))

class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender = db.Column(db.String(80), nullable=False)
    receiver = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(20), default='pending')

class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Otp(db.Model):
    username = db.Column(db.String(80), primary_key=True)
    otp = db.Column(db.String(10), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables automatically
with app.app_context():
    db.create_all()

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
    
    if action == 'signup':
        try:
            new_user = User(username=username, password=password, phone=phone, peer_id=peer_id)
            db.session.add(new_user)
            db.session.commit()
            return jsonify({"success": True, "message": "Account created!"})
        except IntegrityError:
            db.session.rollback()
            return jsonify({"success": False, "error": "Username already exists!"}), 400
            
    elif action == 'login':
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            user.peer_id = peer_id
            db.session.commit()
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Invalid credentials!"}), 401

@app.route('/update_peer', methods=['POST'])
def update_peer():
    data = request.json
    user = User.query.filter_by(username=data.get('username')).first()
    if user:
        user.peer_id = data.get('peer_id')
        db.session.commit()
    return jsonify({"success": True})

@app.route('/search', methods=['GET'])
def search_user():
    query_str = request.args.get('username')
    me = request.args.get('me')
    users = User.query.filter(User.username.like(f'%{query_str}%'), User.username != me).limit(5).all()
    return jsonify([u.username for u in users])

@app.route('/friend_action', methods=['POST'])
def friend_action():
    data = request.json
    action = data.get('action')
    sender = data.get('sender')
    receiver = data.get('receiver')
    
    if action == 'send':
        existing = Friend.query.filter(
            ((Friend.sender == sender) & (Friend.receiver == receiver)) |
            ((Friend.sender == receiver) & (Friend.receiver == sender))
        ).first()
        if not existing:
            new_f = Friend(sender=sender, receiver=receiver)
            db.session.add(new_f)
    elif action == 'accept':
        friend_req = Friend.query.filter_by(sender=receiver, receiver=sender).first()
        if friend_req:
            friend_req.status = 'accepted'
    db.session.commit()
    return jsonify({"success": True})

@app.route('/get_dashboard_data', methods=['GET'])
def get_dashboard_data():
    me = request.args.get('username')
    pending = Friend.query.filter_by(receiver=me, status='pending').all()
    friends = Friend.query.filter((Friend.status == 'accepted') & ((Friend.sender == me) | (Friend.receiver == me))).all()
    
    friend_list = []
    friend_names = set()
    for f in friends:
        fname = f.sender if f.receiver == me else f.receiver
        friend_names.add(fname)
        u = User.query.filter_by(username=fname).first()
        friend_list.append({"username": fname, "peer_id": u.peer_id if u else None})
        
    one_day_ago = datetime.utcnow() - timedelta(days=1)
    status_users = list(friend_names) + [me]
    statuses = Status.query.filter(Status.username.in_(status_users), Status.timestamp >= one_day_ago).order_by(Status.timestamp.desc()).all()
    
    return jsonify({
        "requests": [p.sender for p in pending], 
        "friends": friend_list,
        "statuses": [{"username": s.username, "content": s.content} for s in statuses]
    })

@app.route('/post_status', methods=['POST'])
def post_status():
    data = request.json
    new_s = Status(username=data.get('username'), content=data.get('content'))
    db.session.add(new_s)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/request_otp', methods=['POST'])
def request_otp():
    data = request.json
    username = data.get('username')
    phone = data.get('phone')
    user = User.query.filter_by(username=username, phone=phone).first()
    
    if user:
        otp_val = str(random.randint(1000, 9999))
        existing_otp = Otp.query.filter_by(username=username).first()
        if existing_otp:
            existing_otp.otp = otp_val
            existing_otp.timestamp = datetime.utcnow()
        else:
            new_otp = Otp(username=username, otp=otp_val)
            db.session.add(new_otp)
        db.session.commit()
        return jsonify({"success": True, "demo_otp": otp_val})
        
    return jsonify({"success": False, "error": "Invalid Username or Phone number"}), 400

@app.route('/reset_password', methods=['POST'])
def reset_password():
    data = request.json
    username = data.get('username')
    otp = data.get('otp')
    new_pass = hashlib.sha256(data.get('new_password').encode()).hexdigest()
    
    otp_record = Otp.query.filter_by(username=username, otp=otp).first()
    if otp_record:
        user = User.query.filter_by(username=username).first()
        if user:
            user.password = new_pass
            db.session.delete(otp_record)
            db.session.commit()
            return jsonify({"success": True})
            
    return jsonify({"success": False, "error": "Invalid OTP"}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
