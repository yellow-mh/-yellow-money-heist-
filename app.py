# app.py - Yellow Money Heist Investment Platform
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import secrets
from datetime import datetime, timedelta
import uuid
import re
import logging
from functools import wraps

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///yellowmoney.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
db = SQLAlchemy(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('YellowMoneyHeist')

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20))
    verified = db.Column(db.Boolean, default=False)
    referral_code = db.Column(db.String(10), unique=True)
    referred_by = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class Investment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    plan = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    last_payout = db.Column(db.DateTime)
    active = db.Column(db.Boolean, default=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # deposit, withdrawal, payout, referral
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed
    payment_method = db.Column(db.String(50))
    reference = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

class Payout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    investment_id = db.Column(db.Integer, db.ForeignKey('investment.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payout_date = db.Column(db.DateTime, default=datetime.utcnow)

# Helper Functions
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def generate_referral_code():
    return str(uuid.uuid4())[:8].upper()

def calculate_weekly_payout(investment):
    return investment.amount * 0.01  # 1% weekly

def process_weekly_payouts():
    with app.app_context():
        active_investments = Investment.query.filter_by(active=True).all()
        for investment in active_investments:
            # Check if it's time for a payout (weekly)
            last_payout = investment.last_payout or investment.start_date
            if datetime.utcnow() >= last_payout + timedelta(days=7):
                payout_amount = calculate_weekly_payout(investment)
                
                # Create payout record
                payout = Payout(
                    investment_id=investment.id,
                    amount=payout_amount
                )
                db.session.add(payout)
                
                # Update investment
                investment.last_payout = datetime.utcnow()
                
                # Create transaction
                transaction = Transaction(
                    user_id=investment.user_id,
                    amount=payout_amount,
                    type='payout',
                    status='completed',
                    reference=f'PYT-{secrets.token_hex(5).upper()}'
                )
                db.session.add(transaction)
                
                db.session.commit()
                logger.info(f"Processed payout of ${payout_amount} for investment {investment.id}")

# Routes
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')
        referral_code = request.form.get('referral_code', '').strip()
        
        # Validation
        if not all([username, email, password, phone]):
            flash('Please fill all required fields', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already taken', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        # Create user
        hashed_password = generate_password_hash(password)
        user_referral_code = generate_referral_code()
        
        user = User(
            username=username,
            email=email,
            password=hashed_password,
            phone=phone,
            referral_code=user_referral_code,
            referred_by=referral_code if referral_code else None
        )
        
        db.session.add(user)
        db.session.commit()
        
        # Log in user
        session['user_id'] = user.id
        session['username'] = user.username
        session.permanent = True
        
        flash('Registration successful!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session.permanent = True
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password', 'error')
        return redirect(url_for('login'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    
    # Get active investments
    investments = Investment.query.filter_by(user_id=user.id, active=True).all()
    
    # Calculate total invested
    total_invested = sum(inv.amount for inv in investments)
    
    # Get recent transactions
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc()).limit(5).all()
    
    # Get referral count (simplified)
    referral_count = User.query.filter_by(referred_by=user.referral_code).count()
    
    return render_template('dashboard.html', 
                         user=user,
                         investments=investments,
                         total_invested=total_invested,
                         transactions=transactions,
                         referral_count=referral_count)

@app.route('/invest', methods=['GET', 'POST'])
@login_required
def invest():
    if request.method == 'POST':
        plan = request.form.get('plan')
        amount = float(request.form.get('amount'))
        
        # Validate plan
        valid_plans = {'5': 5, '10': 10, '20': 20, '50': 50}
        if plan not in valid_plans or amount != valid_plans[plan]:
            flash('Invalid investment plan', 'error')
            return redirect(url_for('invest'))
        
        # Create investment
        investment = Investment(
            user_id=session['user_id'],
            amount=amount,
            plan=plan
        )
        db.session.add(investment)
        
        # Create transaction record
        transaction = Transaction(
            user_id=session['user_id'],
            amount=amount,
            type='deposit',
            status='pending',
            payment_method='pending',
            reference=f'INV-{secrets.token_hex(5).upper()}'
        )
        db.session.add(transaction)
        
        db.session.commit()
        
        flash('Investment created successfully! Please complete payment', 'success')
        return redirect(url_for('payment', transaction_id=transaction.id))
    
    return render_template('invest.html')

@app.route('/payment/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def payment(transaction_id):
    transaction = Transaction.query.get_or_404(transaction_id)
    
    if transaction.user_id != session['user_id'] or transaction.type != 'deposit' or transaction.status != 'pending':
        flash('Invalid payment request', 'error')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        payment_method = request.form.get('payment_method')
        
        if payment_method not in ['visa', 'mtn']:
            flash('Invalid payment method', 'error')
            return redirect(url_for('payment', transaction_id=transaction.id))
        
        # In a real app, you would integrate with payment processors here
        # For demo, we'll just mark as completed
        
        transaction.status = 'completed'
        transaction.payment_method = payment_method
        transaction.completed_at = datetime.utcnow()
        
        # If this was a referral, process referral bonus
        user = User.query.get(session['user_id'])
        if user.referred_by:
            referrer = User.query.filter_by(referral_code=user.referred_by).first()
            if referrer:
                referral_bonus = transaction.amount * 0.05  # 5% referral bonus
                referral_transaction = Transaction(
                    user_id=referrer.id,
                    amount=referral_bonus,
                    type='referral',
                    status='completed',
                    payment_method='system',
                    reference=f'REF-{secrets.token_hex(5).upper()}'
                )
                db.session.add(referral_transaction)
                flash(f'Referral bonus of ${referral_bonus:.2f} credited to your referrer!', 'info')
        
        db.session.commit()
        
        flash('Payment completed successfully! Your investment is now active.', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('payment.html', transaction=transaction)

@app.route('/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw():
    if request.method == 'POST':
        amount = float(request.form.get('amount'))
        method = request.form.get('method')
        
        # Basic validation
        if amount <= 0:
            flash('Invalid withdrawal amount', 'error')
            return redirect(url_for('withdraw'))
        
        if method not in ['visa', 'mtn']:
            flash('Invalid withdrawal method', 'error')
            return redirect(url_for('withdraw'))
        
        # Create withdrawal request
        transaction = Transaction(
            user_id=session['user_id'],
            amount=amount,
            type='withdrawal',
            status='pending',
            payment_method=method,
            reference=f'WDR-{secrets.token_hex(5).upper()}'
        )
        db.session.add(transaction)
        db.session.commit()
        
        flash('Withdrawal request submitted. It will be processed within 24 hours.', 'success')
        return redirect(url_for('dashboard'))
    
    # Calculate available balance (simplified)
    user = User.query.get(session['user_id'])
    payouts = Payout.query.join(Investment).filter(Investment.user_id == user.id).all()
    total_payouts = sum(p.amount for p in payouts)
    
    # Get referral earnings
    referral_earnings = Transaction.query.filter_by(
        user_id=user.id, 
        type='referral', 
        status='completed'
    ).all()
    total_referrals = sum(t.amount for t in referral_earnings)
    
    available_balance = total_payouts + total_referrals
    
    return render_template('withdraw.html', available_balance=available_balance)

@app.route('/kyc', methods=['GET', 'POST'])
@login_required
def kyc():
    if request.method == 'POST':
        # In a real app, you would handle file uploads and verification here
        flash('KYC information submitted for verification', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('kyc.html')

@app.route('/referrals')
@login_required
def referrals():
    user = User.query.get(session['user_id'])
    
    # Get referral stats
    referred_users = User.query.filter_by(referred_by=user.referral_code).all()
    referral_earnings = Transaction.query.filter_by(
        user_id=user.id, 
        type='referral', 
        status='completed'
    ).all()
    total_earned = sum(t.amount for t in referral_earnings)
    
    return render_template('referrals.html', 
                         user=user,
                         referred_users=referred_users,
                         referral_earnings=referral_earnings,
                         total_earned=total_earned)

# API Endpoints
@app.route('/api/check_username')
def check_username():
    username = request.args.get('username')
    exists = User.query.filter_by(username=username).first() is not None
    return jsonify({'exists': exists})

@app.route('/api/check_email')
def check_email():
    email = request.args.get('email')
    exists = User.query.filter_by(email=email).first() is not None
    return jsonify({'exists': exists})

# Error Handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# Templates (embedded in Python for single-file deployment)
@app.context_processor
def inject_globals():
    return {
        'site_name': 'Yellow Money Heist',
        'current_year': datetime.now().year,
        'support_email': 'yellowmoneyheist@gmail.com',
        'support_phone': '+2560706322145',
        'mtn_account': '0768568972'
    }

def render_template(template_name, **context):
    templates = {
        'home.html': '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ site_name }} - Smart Investments</title>
    <style>
        :root {
            --primary: #FFD700;
            --secondary: #000;
            --accent: #FFA500;
            --light: #FFF8DC;
            --dark: #333;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            background-color: #f5f5f5;
            color: var(--dark);
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        header {
            background-color: var(--primary);
            color: var(--secondary);
            padding: 20px 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .logo {
            font-size: 24px;
            font-weight: bold;
            color: var(--secondary);
            text-decoration: none;
        }
        .nav-links {
            display: flex;
            gap: 20px;
        }
        .nav-links a {
            color: var(--secondary);
            text-decoration: none;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--accent);
        }
        .auth-buttons {
            display: flex;
            gap: 10px;
        }
        .btn {
            padding: 10px 20px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        .btn-primary {
            background-color: var(--secondary);
            color: white;
        }
        .btn-outline {
            border: 1px solid var(--secondary);
            color: var(--secondary);
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        .hero {
            padding: 80px 0;
            text-align: center;
            background: linear-gradient(rgba(255, 215, 0, 0.1), rgba(255, 215, 0, 0.1)), url('https://via.placeholder.com/1200x400') no-repeat center center/cover;
        }
        .hero h1 {
            font-size: 48px;
            margin-bottom: 20px;
            color: var(--secondary);
        }
        .hero p {
            font-size: 20px;
            max-width: 800px;
            margin: 0 auto 30px;
            color: var(--dark);
        }
        .plans {
            padding: 60px 0;
            background-color: white;
        }
        .section-title {
            text-align: center;
            margin-bottom: 40px;
            font-size: 36px;
            color: var(--secondary);
        }
        .plan-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 30px;
        }
        .plan-card {
            background-color: var(--light);
            border-radius: 10px;
            padding: 30px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
            transition: all 0.3s ease;
        }
        .plan-card:hover {
            transform: translateY(-10px);
            box-shadow: 0 15px 30px rgba(0,0,0,0.1);
        }
        .plan-card h3 {
            font-size: 24px;
            margin-bottom: 15px;
            color: var(--secondary);
        }
        .plan-card .price {
            font-size: 36px;
            font-weight: bold;
            color: var(--accent);
            margin-bottom: 20px;
        }
        .plan-card .features {
            margin-bottom: 30px;
            text-align: left;
        }
        .plan-card .features li {
            margin-bottom: 10px;
            list-style-type: none;
            padding-left: 25px;
            position: relative;
        }
        .plan-card .features li:before {
            content: '✓';
            position: absolute;
            left: 0;
            color: var(--accent);
            font-weight: bold;
        }
        footer {
            background-color: var(--secondary);
            color: white;
            padding: 40px 0;
            text-align: center;
        }
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 20px;
        }
        .footer-links a {
            color: white;
            text-decoration: none;
        }
        .footer-links a:hover {
            color: var(--primary);
        }
        .social-links {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-bottom: 20px;
        }
        .social-links a {
            color: white;
            font-size: 20px;
        }
        .copyright {
            font-size: 14px;
            opacity: 0.8;
        }
        @media (max-width: 768px) {
            .nav-links {
                display: none;
            }
            .hero h1 {
                font-size: 36px;
            }
            .hero p {
                font-size: 18px;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <nav>
                <a href="{{ url_for('home') }}" class="logo">{{ site_name }}</a>
                <div class="nav-links">
                    <a href="#how-it-works">How It Works</a>
                    <a href="#plans">Investment Plans</a>
                    <a href="#testimonials">Testimonials</a>
                    <a href="#faq">FAQ</a>
                </div>
                <div class="auth-buttons">
                    <a href="{{ url_for('login') }}" class="btn btn-outline">Login</a>
                    <a href="{{ url_for('register') }}" class="btn btn-primary">Register</a>
                </div>
            </nav>
        </div>
    </header>

    <section class="hero">
        <div class="container">
            <h1>Earn 1% Weekly Returns on Your Investments</h1>
            <p>Join thousands of investors who are growing their wealth with our proven investment platform. Start with as little as $5 and watch your money grow.</p>
            <div>
                <a href="{{ url_for('register') }}" class="btn btn-primary">Get Started Now</a>
            </div>
        </div>
    </section>

    <section id="how-it-works" class="container" style="padding: 60px 0;">
        <h2 class="section-title">How Yellow Money Heist Works</h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 30px;">
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 15px; color: var(--accent);">1</div>
                <h3 style="margin-bottom: 15px;">Create Account</h3>
                <p>Sign up in minutes with your basic information and verify your account.</p>
            </div>
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 15px; color: var(--accent);">2</div>
                <h3 style="margin-bottom: 15px;">Choose Investment Plan</h3>
                <p>Select from our range of investment plans that fit your budget.</p>
            </div>
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 15px; color: var(--accent);">3</div>
                <h3 style="margin-bottom: 15px;">Make Deposit</h3>
                <p>Fund your account using Visa card or MTN mobile money.</p>
            </div>
            <div style="text-align: center; padding: 20px;">
                <div style="font-size: 48px; margin-bottom: 15px; color: var(--accent);">4</div>
                <h3 style="margin-bottom: 15px;">Earn Weekly</h3>
                <p>Receive 1% of your investment every week automatically.</p>
            </div>
        </div>
    </section>

    <section id="plans" class="plans">
        <div class="container">
            <h2 class="section-title">Investment Plans</h2>
            <div class="plan-cards">
                <div class="plan-card">
                    <h3>Starter</h3>
                    <div class="price">$5</div>
                    <ul class="features">
                        <li>1% Weekly Returns</li>
                        <li>Flexible Withdrawals</li>
                        <li>24/7 Support</li>
                        <li>Basic Account</li>
                    </ul>
                    <a href="{{ url_for('register') }}" class="btn btn-primary">Get Started</a>
                </div>
                <div class="plan-card">
                    <h3>Basic</h3>
                    <div class="price">$10</div>
                    <ul class="features">
                        <li>1% Weekly Returns</li>
                        <li>Flexible Withdrawals</li>
                        <li>Priority Support</li>
                        <li>Standard Account</li>
                    </ul>
                    <a href="{{ url_for('register') }}" class="btn btn-primary">Get Started</a>
                </div>
                <div class="plan-card">
                    <h3>Premium</h3>
                    <div class="price">$20</div>
                    <ul class="features">
                        <li>1% Weekly Returns</li>
                        <li>Flexible Withdrawals</li>
                        <li>VIP Support</li>
                        <li>Premium Account</li>
                    </ul>
                    <a href="{{ url_for('register') }}" class="btn btn-primary">Get Started</a>
                </div>
                <div class="plan-card">
                    <h3>Elite</h3>
                    <div class="price">$50</div>
                    <ul class="features">
                        <li>1% Weekly Returns</li>
                        <li>Flexible Withdrawals</li>
                        <li>24/7 Dedicated Support</li>
                        <li>Elite Account</li>
                    </ul>
                    <a href="{{ url_for('register') }}" class="btn btn-primary">Get Started</a>
                </div>
            </div>
        </div>
    </section>

    <section id="testimonials" style="padding: 60px 0; background-color: var(--light);">
        <div class="container">
            <h2 class="section-title">What Our Investors Say</h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px;">
                <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.05);">
                    <div style="display: flex; align-items: center; margin-bottom: 20px;">
                        <div style="width: 50px; height: 50px; background-color: var(--accent); border-radius: 50%; margin-right: 15px;"></div>
                        <div>
                            <h4 style="margin: 0;">John D.</h4>
                            <p style="margin: 0; opacity: 0.7;">Investor since 2022</p>
                        </div>
                    </div>
                    <p>"I started with $20 and now I'm making consistent weekly returns. The platform is easy to use and payments are always on time."</p>
                </div>
                <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.05);">
                    <div style="display: flex; align-items: center; margin-bottom: 20px;">
                        <div style="width: 50px; height: 50px; background-color: var(--accent); border-radius: 50%; margin-right: 15px;"></div>
                        <div>
                            <h4 style="margin: 0;">Sarah K.</h4>
                            <p style="margin: 0; opacity: 0.7;">Investor since 2023</p>
                        </div>
                    </div>
                    <p>"The referral program is amazing! I've earned over $100 just by inviting my friends to join the platform."</p>
                </div>
                <div style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.05);">
                    <div style="display: flex; align-items: center; margin-bottom: 20px;">
                        <div style="width: 50px; height: 50px; background-color: var(--accent); border-radius: 50%; margin-right: 15px;"></div>
                        <div>
                            <h4 style="margin: 0;">Michael T.</h4>
                            <p style="margin: 0; opacity: 0.7;">Investor since 2023</p>
                        </div>
                    </div>
                    <p>"I was skeptical at first but after receiving my first payout, I increased my investment. The team is professional and responsive."</p>
                </div>
            </div>
        </div>
    </section>

    <section id="faq" style="padding: 60px 0;">
        <div class="container">
            <h2 class="section-title">Frequently Asked Questions</h2>
            <div style="max-width: 800px; margin: 0 auto;">
                <div style="margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 20px;">
                    <h3 style="margin-bottom: 10px;">How do the weekly payouts work?</h3>
                    <p>Every week, you'll receive 1% of your invested amount directly to your account balance. You can withdraw these earnings or reinvest them.</p>
                </div>
                <div style="margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 20px;">
                    <h3 style="margin-bottom: 10px;">What payment methods do you accept?</h3>
                    <p>We accept Visa cards and MTN mobile money for deposits and withdrawals.</p>
                </div>
                <div style="margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 20px;">
                    <h3 style="margin-bottom: 10px;">Is there a referral program?</h3>
                    <p>Yes! You earn 5% of your referral's first deposit. There's no limit to how much you can earn through referrals.</p>
                </div>
                <div style="margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 20px;">
                    <h3 style="margin-bottom: 10px;">How do I withdraw my earnings?</h3>
                    <p>You can request a withdrawal from your dashboard. Withdrawals are processed within 24 hours to your preferred payment method.</p>
                </div>
                <div style="margin-bottom: 20px;">
                    <h3 style="margin-bottom: 10px;">Is my investment secure?</h3>
                    <p>We implement bank-level security measures including encryption and two-factor authentication to protect your funds and personal information.</p>
                </div>
            </div>
        </div>
    </section>

    <section style="padding: 60px 0; background-color: var(--primary); text-align: center;">
        <div class="container">
            <h2 style="margin-bottom: 20px;">Ready to Start Earning?</h2>
            <p style="max-width: 600px; margin: 0 auto 30px;">Join thousands of satisfied investors today and start growing your wealth with our simple and transparent investment platform.</p>
            <a href="{{ url_for('register') }}" class="btn btn-primary">Sign Up Now</a>
        </div>
    </section>

    <footer>
        <div class="container">
            <div class="footer-links">
                <a href="{{ url_for('home') }}">Home</a>
                <a href="#how-it-works">How It Works</a>
                <a href="#plans">Plans</a>
                <a href="#faq">FAQ</a>
                <a href="#">Contact</a>
                <a href="#">Terms</a>
                <a href="#">Privacy</a>
            </div>
            <div class="social-links">
                <a href="#"><i class="fab fa-facebook"></i></a>
                <a href="#"><i class="fab fa-twitter"></i></a>
                <a href="#"><i class="fab fa-instagram"></i></a>
                <a href="#"><i class="fab fa-telegram"></i></a>
            </div>
            <div class="contact-info">
                <p>Email: {{ support_email }} | Phone: {{ support_phone }}</p>
            </div>
            <p class="copyright">© {{ current_year }} {{ site_name }}. All rights reserved.</p>
        </div>
    </footer>

    <script>
        // Simple form validation
        document.addEventListener('DOMContentLoaded', function() {
            // This would be enhanced with actual form validation in a real implementation
            console.log('Yellow Money Heist - Secure Investment Platform');
        });
    </script>
</body>
</html>
        ''',
        'register.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="auth-container">
    <h2>Create Your Account</h2>
    <form action="{{ url_for('register') }}" method="POST">
        <div class="form-group">
            <label for="username">Username</label>
            <input type="text" id="username" name="username" required>
            <small id="username-availability"></small>
        </div>
        <div class="form-group">
            <label for="email">Email Address</label>
            <input type="email" id="email" name="email" required>
            <small id="email-availability"></small>
        </div>
        <div class="form-group">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required>
        </div>
        <div class="form-group">
            <label for="phone">Phone Number</label>
            <input type="tel" id="phone" name="phone" required>
        </div>
        <div class="form-group">
            <label for="referral_code">Referral Code (optional)</label>
            <input type="text" id="referral_code" name="referral_code">
        </div>
        <div class="form-group">
            <input type="checkbox" id="terms" name="terms" required>
            <label for="terms">I agree to the <a href="#">Terms of Service</a> and <a href="#">Privacy Policy</a></label>
        </div>
        <button type="submit" class="btn btn-primary">Register</button>
    </form>
    <p>Already have an account? <a href="{{ url_for('login') }}">Login here</a></p>
</div>
<script>
    // Check username availability
    document.getElementById('username').addEventListener('blur', function() {
        const username = this.value;
        if(username.length > 3) {
            fetch(`/api/check_username?username=${username}`)
                .then(response => response.json())
                .then(data => {
                    const availability = document.getElementById('username-availability');
                    if(data.exists) {
                        availability.textContent = 'Username already taken';
                        availability.style.color = 'red';
                    } else {
                        availability.textContent = 'Username available';
                        availability.style.color = 'green';
                    }
                });
        }
    });

    // Check email availability
    document.getElementById('email').addEventListener('blur', function() {
        const email = this.value;
        if(email.includes('@')) {
            fetch(`/api/check_email?email=${email}`)
                .then(response => response.json())
                .then(data => {
                    const availability = document.getElementById('email-availability');
                    if(data.exists) {
                        availability.textContent = 'Email already registered';
                        availability.style.color = 'red';
                    } else {
                        availability.textContent = 'Email available';
                        availability.style.color = 'green';
                    }
                });
        }
    });
</script>
{% endblock %}
        ''',
        'login.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="auth-container">
    <h2>Login to Your Account</h2>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}
    <form action="{{ url_for('login') }}" method="POST">
        <div class="form-group">
            <label for="username">Username or Email</label>
            <input type="text" id="username" name="username" required>
        </div>
        <div class="form-group">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required>
        </div>
        <div class="form-group">
            <input type="checkbox" id="remember" name="remember">
            <label for="remember">Remember me</label>
            <a href="#" style="float: right;">Forgot password?</a>
        </div>
        <button type="submit" class="btn btn-primary">Login</button>
    </form>
    <p>Don't have an account? <a href="{{ url_for('register') }}">Register here</a></p>
</div>
{% endblock %}
        ''',
        'dashboard.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="dashboard-container">
    <div class="welcome-banner">
        <h2>Welcome back, {{ user.username }}!</h2>
        <p>Your investment journey continues. Check your stats below.</p>
    </div>

    <div class="stats-grid">
        <div class="stat-card">
            <h3>Total Invested</h3>
            <p>${{ "%.2f"|format(total_invested) }}</p>
        </div>
        <div class="stat-card">
            <h3>Active Investments</h3>
            <p>{{ investments|length }}</p>
        </div>
        <div class="stat-card">
            <h3>Referrals</h3>
            <p>{{ referral_count }}</p>
        </div>
        <div class="stat-card">
            <h3>Account Status</h3>
            <p>{{ "Verified" if user.verified else "Pending Verification" }}</p>
        </div>
    </div>

    <div class="dashboard-sections">
        <div class="investments-section">
            <h3>Your Active Investments</h3>
            {% if investments %}
                <div class="investments-list">
                    {% for inv in investments %}
                    <div class="investment-item">
                        <div>
                            <h4>${{ "%.2f"|format(inv.amount) }} Plan</h4>
                            <p>Started on {{ inv.start_date.strftime('%Y-%m-%d') }}</p>
                        </div>
                        <div>
                            <p>Next payout: {% if inv.last_payout %}{{ (inv.last_payout + timedelta(days=7)).strftime('%Y-%m-%d') }}{% else %}{{ (inv.start_date + timedelta(days=7)).strftime('%Y-%m-%d') }}{% endif %}</p>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            {% else %}
                <p>You don't have any active investments yet.</p>
                <a href="{{ url_for('invest') }}" class="btn btn-primary">Start Investing</a>
            {% endif %}
        </div>

        <div class="transactions-section">
            <h3>Recent Transactions</h3>
            {% if transactions %}
                <div class="transactions-list">
                    {% for trans in transactions %}
                    <div class="transaction-item">
                        <div>
                            <h4>{{ trans.type|title }}</h4>
                            <p>{{ trans.created_at.strftime('%Y-%m-%d %H:%M') }}</p>
                        </div>
                        <div class="amount {{ trans.type }}">
                            ${{ "%.2f"|format(trans.amount) }}
                        </div>
                    </div>
                    {% endfor %}
                </div>
                <a href="#" class="view-all">View All Transactions</a>
            {% else %}
                <p>No transactions yet.</p>
            {% endif %}
        </div>
    </div>

    <div class="quick-actions">
        <a href="{{ url_for('invest') }}" class="btn btn-primary">Make Investment</a>
        <a href="{{ url_for('withdraw') }}" class="btn btn-outline">Withdraw Funds</a>
        <a href="{{ url_for('referrals') }}" class="btn btn-outline">Referral Program</a>
    </div>
</div>
{% endblock %}
        ''',
        'invest.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="invest-container">
    <h2>Choose Your Investment Plan</h2>
    <p>Select from our range of investment plans and start earning 1% weekly returns.</p>

    <div class="investment-plans">
        <div class="plan-card">
            <h3>Starter Plan</h3>
            <div class="price">$5</div>
            <ul class="features">
                <li>1% Weekly Returns ($0.05/week)</li>
                <li>Flexible Withdrawal</li>
                <li>Basic Support</li>
            </ul>
            <form action="{{ url_for('invest') }}" method="POST">
                <input type="hidden" name="plan" value="5">
                <input type="hidden" name="amount" value="5">
                <button type="submit" class="btn btn-primary">Invest Now</button>
            </form>
        </div>

        <div class="plan-card recommended">
            <div class="recommended-badge">Popular</div>
            <h3>Basic Plan</h3>
            <div class="price">$10</div>
            <ul class="features">
                <li>1% Weekly Returns ($0.10/week)</li>
                <li>Flexible Withdrawal</li>
                <li>Priority Support</li>
            </ul>
            <form action="{{ url_for('invest') }}" method="POST">
                <input type="hidden" name="plan" value="10">
                <input type="hidden" name="amount" value="10">
                <button type="submit" class="btn btn-primary">Invest Now</button>
            </form>
        </div>

        <div class="plan-card">
            <h3>Premium Plan</h3>
            <div class="price">$20</div>
            <ul class="features">
                <li>1% Weekly Returns ($0.20/week)</li>
                <li>Flexible Withdrawal</li>
                <li>VIP Support</li>
            </ul>
            <form action="{{ url_for('invest') }}" method="POST">
                <input type="hidden" name="plan" value="20">
                <input type="hidden" name="amount" value="20">
                <button type="submit" class="btn btn-primary">Invest Now</button>
            </form>
        </div>

        <div class="plan-card">
            <h3>Elite Plan</h3>
            <div class="price">$50</div>
            <ul class="features">
                <li>1% Weekly Returns ($0.50/week)</li>
                <li>Flexible Withdrawal</li>
                <li>Dedicated Support</li>
            </ul>
            <form action="{{ url_for('invest') }}" method="POST">
                <input type="hidden" name="plan" value="50">
                <input type="hidden" name="amount" value="50">
                <button type="submit" class="btn btn-primary">Invest Now</button>
            </form>
        </div>
    </div>

    <div class="investment-info">
        <h3>How It Works</h3>
        <ol>
            <li>Choose your investment plan</li>
            <li>Complete payment via Visa or MTN Mobile Money</li>
            <li>Start receiving 1% of your investment every week</li>
            <li>Withdraw your earnings anytime or reinvest</li>
        </ol>
    </div>
</div>
{% endblock %}
        ''',
        'payment.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="payment-container">
    <h2>Complete Your Investment</h2>
    <div class="payment-summary">
        <h3>Investment Summary</h3>
        <p>Amount: ${{ "%.2f"|format(transaction.amount) }}</p>
        <p>Reference: {{ transaction.reference }}</p>
    </div>

    <form action="{{ url_for('payment', transaction_id=transaction.id) }}" method="POST">
        <div class="payment-methods">
            <div class="payment-method">
                <input type="radio" id="visa" name="payment_method" value="visa" checked>
                <label for="visa">
                    <img src="https://via.placeholder.com/100x60?text=VISA" alt="Visa">
                    <span>Pay with Visa Card</span>
                </label>
            </div>
            <div class="payment-method">
                <input type="radio" id="mtn" name="payment_method" value="mtn">
                <label for="mtn">
                    <img src="https://via.placeholder.com/100x60?text=MTN" alt="MTN">
                    <span>Pay with MTN Mobile Money</span>
                </label>
            </div>
        </div>

        <div id="visa-details" class="payment-details">
            <div class="form-group">
                <label for="card-number">Card Number</label>
                <input type="text" id="card-number" placeholder="1234 5678 9012 3456">
            </div>
            <div class="form-group">
                <label for="card-name">Cardholder Name</label>
                <input type="text" id="card-name" placeholder="John Doe">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label for="expiry">Expiry Date</label>
                    <input type="text" id="expiry" placeholder="MM/YY">
                </div>
                <div class="form-group">
                    <label for="cvv">CVV</label>
                    <input type="text" id="cvv" placeholder="123">
                </div>
            </div>
        </div>

        <div id="mtn-details" class="payment-details" style="display: none;">
            <div class="form-group">
                <p>Send {{ "%.2f"|format(transaction.amount) }} UGX to MTN Mobile Money number:</p>
                <p class="mtn-number">{{ mtn_account }}</p>
                <p>Use your reference: <strong>{{ transaction.reference }}</strong></p>
            </div>
            <div class="form-group">
                <label for="mtn-phone">Your MTN Number</label>
                <input type="tel" id="mtn-phone" name="mtn_phone" placeholder="07XXXXXXXX">
            </div>
        </div>

        <button type="submit" class="btn btn-primary">Complete Payment</button>
    </form>
</div>

<script>
    // Show/hide payment details based on selection
    document.querySelectorAll('input[name="payment_method"]').forEach(radio => {
        radio.addEventListener('change', function() {
            document.getElementById('visa-details').style.display = 
                this.value === 'visa' ? 'block' : 'none';
            document.getElementById('mtn-details').style.display = 
                this.value === 'mtn' ? 'block' : 'none';
        });
    });
</script>
{% endblock %}
        ''',
        'withdraw.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="withdraw-container">
    <h2>Withdraw Funds</h2>
    <div class="balance-info">
        <p>Available Balance: <strong>${{ "%.2f"|format(available_balance) }}</strong></p>
    </div>

    <form action="{{ url_for('withdraw') }}" method="POST">
        <div class="form-group">
            <label for="amount">Amount to Withdraw</label>
            <input type="number" id="amount" name="amount" min="5" max="{{ available_balance }}" step="0.01" required>
            <small>Minimum withdrawal: $5.00</small>
        </div>

        <div class="form-group">
            <label>Withdrawal Method</label>
            <div class="payment-methods">
                <div class="payment-method">
                    <input type="radio" id="withdraw-visa" name="method" value="visa" checked>
                    <label for="withdraw-visa">
                        <img src="https://via.placeholder.com/100x60?text=VISA" alt="Visa">
                        <span>Visa Card</span>
                    </label>
                </div>
                <div class="payment-method">
                    <input type="radio" id="withdraw-mtn" name="method" value="mtn">
                    <label for="withdraw-mtn">
                        <img src="https://via.placeholder.com/100x60?text=MTN" alt="MTN">
                        <span>MTN Mobile Money</span>
                    </label>
                </div>
            </div>
        </div>

        <div id="withdraw-visa-details" class="payment-details">
            <div class="form-group">
                <label for="card-number">Card Number</label>
                <input type="text" id="card-number" placeholder="1234 5678 9012 3456">
            </div>
        </div>

        <div id="withdraw-mtn-details" class="payment-details" style="display: none;">
            <div class="form-group">
                <label for="mtn-phone">MTN Mobile Money Number</label>
                <input type="tel" id="mtn-phone" name="mtn_phone" placeholder="07XXXXXXXX">
            </div>
        </div>

        <button type="submit" class="btn btn-primary">Request Withdrawal</button>
    </form>

    <div class="withdrawal-info">
        <h3>Withdrawal Information</h3>
        <ul>
            <li>Withdrawals are processed within 24 hours</li>
            <li>Minimum withdrawal amount is $5.00</li>
            <li>No withdrawal fees</li>
        </ul>
    </div>
</div>

<script>
    // Show/hide withdrawal details based on selection
    document.querySelectorAll('input[name="method"]').forEach(radio => {
        radio.addEventListener('change', function() {
            document.getElementById('withdraw-visa-details').style.display = 
                this.value === 'visa' ? 'block' : 'none';
            document.getElementById('withdraw-mtn-details').style.display = 
                this.value === 'mtn' ? 'block' : 'none';
        });
    });
</script>
{% endblock %}
        ''',
        'kyc.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="kyc-container">
    <h2>Complete KYC Verification</h2>
    <p>To comply with financial regulations and ensure the security of all transactions, we require you to complete KYC (Know Your Customer) verification.</p>

    <form action="{{ url_for('kyc') }}" method="POST" enctype="multipart/form-data">
        <div class="form-group">
            <label for="full-name">Full Name (as on ID)</label>
            <input type="text" id="full-name" name="full_name" required>
        </div>

        <div class="form-group">
            <label for="id-type">ID Type</label>
            <select id="id-type" name="id_type" required>
                <option value="">Select ID Type</option>
                <option value="passport">Passport</option>
                <option value="national_id">National ID</option>
                <option value="driving_license">Driving License</option>
            </select>
        </div>

        <div class="form-group">
            <label for="id-number">ID Number</label>
            <input type="text" id="id-number" name="id_number" required>
        </div>

        <div class="form-group">
            <label for="id-front">ID Front Photo</label>
            <input type="file" id="id-front" name="id_front" accept="image/*" required>
            <small>Clear photo of the front side of your ID</small>
        </div>

        <div class="form-group">
            <label for="id-back">ID Back Photo</label>
            <input type="file" id="id-back" name="id_back" accept="image/*">
            <small>Clear photo of the back side of your ID (if applicable)</small>
        </div>

        <div class="form-group">
            <label for="selfie">Selfie with ID</label>
            <input type="file" id="selfie" name="selfie" accept="image/*" required>
            <small>Clear selfie holding your ID next to your face</small>
        </div>

        <div class="form-group">
            <input type="checkbox" id="kyc-consent" name="kyc_consent" required>
            <label for="kyc-consent">I consent to the processing of my personal data for verification purposes</label>
        </div>

        <button type="submit" class="btn btn-primary">Submit for Verification</button>
    </form>

    <div class="kyc-info">
        <h3>Why KYC is Required</h3>
        <ul>
            <li>Prevents fraud and money laundering</li>
            <li>Protects your account from unauthorized access</li>
            <li>Required by financial regulations</li>
            <li>Enables higher withdrawal limits</li>
        </ul>
        <p>Your documents are securely stored and encrypted. We do not share your information with third parties.</p>
    </div>
</div>
{% endblock %}
        ''',
        'referrals.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="referrals-container">
    <h2>Your Referral Program</h2>
    
    <div class="referral-stats">
        <div class="stat-card">
            <h3>Your Referral Code</h3>
            <div class="referral-code">{{ user.referral_code }}</div>
            <button onclick="copyReferralCode()" class="btn btn-outline">Copy Code</button>
        </div>
        <div class="stat-card">
            <h3>Total Referrals</h3>
            <p>{{ referred_users|length }}</p>
        </div>
        <div class="stat-card">
            <h3>Total Earned</h3>
            <p>${{ "%.2f"|format(total_earned) }}</p>
        </div>
    </div>

    <div class="referral-share">
        <h3>Share Your Referral Link</h3>
        <div class="share-link">
            <input type="text" id="referral-link" value="{{ request.host_url }}register?ref={{ user.referral_code }}" readonly>
            <button onclick="copyReferralLink()" class="btn btn-primary">Copy Link</button>
        </div>
        <div class="share-buttons">
            <button class="btn btn-outline"><i class="fab fa-facebook"></i> Share on Facebook</button>
            <button class="btn btn-outline"><i class="fab fa-whatsapp"></i> Share on WhatsApp</button>
            <button class="btn btn-outline"><i class="fab fa-telegram"></i> Share on Telegram</button>
        </div>
    </div>

    <div class="referral-details">
        <h3>How It Works</h3>
        <ol>
            <li>Share your referral link with friends</li>
            <li>They sign up using your link</li>
            <li>They make their first deposit</li>
            <li>You earn 5% of their first deposit</li>
            <li>No limit on how much you can earn!</li>
        </ol>
    </div>

    {% if referred_users %}
    <div class="referral-list">
        <h3>Your Referrals</h3>
        <table>
            <thead>
                <tr>
                    <th>Username</th>
                    <th>Join Date</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for ref in referred_users %}
                <tr>
                    <td>{{ ref.username }}</td>
                    <td>{{ ref.created_at.strftime('%Y-%m-%d') }}</td>
                    <td>{{ "Active" if ref.verified else "Pending" }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    {% if referral_earnings %}
    <div class="earnings-list">
        <h3>Your Referral Earnings</h3>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>From</th>
                </tr>
            </thead>
            <tbody>
                {% for earning in referral_earnings %}
                <tr>
                    <td>{{ earning.created_at.strftime('%Y-%m-%d') }}</td>
                    <td>${{ "%.2f"|format(earning.amount) }}</td>
                    <td>{{ earning.reference }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}
</div>

<script>
    function copyReferralCode() {
        navigator.clipboard.writeText("{{ user.referral_code }}");
        alert("Referral code copied to clipboard!");
    }

    function copyReferralLink() {
        const link = document.getElementById('referral-link');
        link.select();
        navigator.clipboard.writeText(link.value);
        alert("Referral link copied to clipboard!");
    }
</script>
{% endblock %}
        ''',
        '404.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="error-container">
    <h1>404 - Page Not Found</h1>
    <p>The page you're looking for doesn't exist or has been moved.</p>
    <a href="{{ url_for('home') }}" class="btn btn-primary">Return Home</a>
</div>
{% endblock %}
        ''',
        '500.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="error-container">
    <h1>500 - Server Error</h1>
    <p>Something went wrong on our end. Please try again later.</p>
    <a href="{{ url_for('home') }}" class="btn btn-primary">Return Home</a>
</div>
{% endblock %}
        ''',
        'layout.html': '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ site_name }}{% endblock %}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css">
    <style>
        :root {
            --primary: #FFD700;
            --secondary: #000;
            --accent: #FFA500;
            --light: #FFF8DC;
            --dark: #333;
            --success: #28a745;
            --danger: #dc3545;
            --info: #17a2b8;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        body {
            background-color: #f5f5f5;
            color: var(--dark);
            line-height: 1.6;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        header {
            background-color: var(--primary);
            color: var(--secondary);
            padding: 15px 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .logo {
            font-size: 24px;
            font-weight: bold;
            color: var(--secondary);
            text-decoration: none;
        }
        .nav-links {
            display: flex;
            gap: 20px;
        }
        .nav-links a {
            color: var(--secondary);
            text-decoration: none;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--accent);
        }
        .user-menu {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .user-menu .username {
            font-weight: 500;
        }
        .btn {
            padding: 8px 16px;
            border-radius: 5px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.3s ease;
            display: inline-block;
            border: none;
            cursor: pointer;
        }
        .btn-primary {
            background-color: var(--secondary);
            color: white;
        }
        .btn-outline {
            border: 1px solid var(--secondary);
            color: var(--secondary);
            background: none;
        }
        .btn-success {
            background-color: var(--success);
            color: white;
        }
        .btn-danger {
            background-color: var(--danger);
            color: white;
        }
        .btn-info {
            background-color: var(--info);
            color: white;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            opacity: 0.9;
        }
        main {
            min-height: calc(100vh - 150px);
            padding: 30px 0;
        }
        footer {
            background-color: var(--secondary);
            color: white;
            padding: 30px 0;
            text-align: center;
        }
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 20px;
        }
        .footer-links a {
            color: white;
            text-decoration: none;
        }
        .footer-links a:hover {
            color: var(--primary);
        }
        .copyright {
            font-size: 14px;
            opacity: 0.8;
        }
        .alert {
            padding: 10px 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .alert-success {
            background-color: #d4edda;
            color: #155724;
        }
        .alert-error {
            background-color: #f8d7da;
            color: #721c24;
        }
        .alert-info {
            background-color: #d1ecf1;
            color: #0c5460;
        }
        .auth-container {
            max-width: 500px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
        }
        .auth-container h2 {
            margin-bottom: 20px;
            text-align: center;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
        }
        .form-group input, 
        .form-group select, 
        .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        .form-group input[type="checkbox"] {
            width: auto;
            margin-right: 10px;
        }
        .form-row {
            display: flex;
            gap: 15px;
        }
        .form-row .form-group {
            flex: 1;
        }
        .dashboard-container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .welcome-banner {
            background: linear-gradient(rgba(255, 215, 0, 0.1), rgba(255, 215, 0, 0.1)), url('https://via.placeholder.com/1200x200') no-repeat center center/cover;
            padding: 40px;
            border-radius: 10px;
            margin-bottom: 30px;
            color: var(--dark);
        }
        .welcome-banner h2 {
            margin-bottom: 10px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
            text-align: center;
        }
        .stat-card h3 {
            font-size: 16px;
            margin-bottom: 10px;
            color: var(--dark);
        }
        .stat-card p {
            font-size: 24px;
            font-weight: bold;
            color: var(--accent);
        }
        .dashboard-sections {
            display: grid;
            grid-template-columns: 1fr;
            gap: 30px;
        }
        @media (min-width: 992px) {
            .dashboard-sections {
                grid-template-columns: 1fr 1fr;
            }
        }
        .investments-section, .transactions-section {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
        }
        .investments-section h3, .transactions-section h3 {
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }
        .investments-list, .transactions-list {
            display: grid;
            gap: 15px;
        }
        .investment-item, .transaction-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            background: var(--light);
            border-radius: 5px;
        }
        .transaction-item .amount {
            font-weight: bold;
        }
        .transaction-item .deposit {
            color: var(--success);
        }
        .transaction-item .withdrawal {
            color: var(--danger);
        }
        .transaction-item .payout {
            color: var(--accent);
        }
        .transaction-item .referral {
            color: var(--info);
        }
        .view-all {
            display: block;
            text-align: right;
            margin-top: 15px;
            color: var(--accent);
            text-decoration: none;
        }
        .quick-actions {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-top: 30px;
        }
        .invest-container, .withdraw-container, .kyc-container, .referrals-container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
        }
        .investment-plans {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 30px;
            margin: 40px 0;
        }
        .plan-card {
            background: var(--light);
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.05);
            position: relative;
            transition: all 0.3s ease;
        }
        .plan-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        }
        .plan-card.recommended {
            border: 2px solid var(--accent);
        }
        .recommended-badge {
            position: absolute;
            top: -10px;
            right: 20px;
            background: var(--accent);
            color: white;
            padding: 5px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .plan-card h3 {
            margin-bottom: 15px;
            text-align: center;
        }
        .plan-card .price {
            font-size: 28px;
            font-weight: bold;
            text-align: center;
            color: var(--accent);
            margin-bottom: 20px;
        }
        .plan-card .features {
            margin-bottom: 25px;
        }
        .plan-card .features li {
            margin-bottom: 10px;
            list-style-type: none;
            padding-left: 25px;
            position: relative;
        }
        .plan-card .features li:before {
            content: '✓';
            position: absolute;
            left: 0;
            color: var(--accent);
            font-weight: bold;
        }
        .plan-card button {
            width: 100%;
        }
        .investment-info {
            margin-top: 40px;
        }
        .investment-info ol {
            padding-left: 20px;
            margin-top: 15px;
        }
        .investment-info li {
            margin-bottom: 10px;
        }
        .payment-methods {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .payment-method {
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 15px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .payment-method:hover {
            border-color: var(--accent);
        }
        .payment-method input[type="radio"] {
            display: none;
        }
        .payment-method input[type="radio"]:checked + label {
            color: var(--accent);
        }
        .payment-method label {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 10px;
            cursor: pointer;
        }
        .payment-method img {
            height: 40px;
        }
        .payment-details {
            margin: 20px 0;
            padding: 20px;
            background: var(--light);
            border-radius: 5px;
        }
        .balance-info {
            background: var(--light);
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            text-align: center;
        }
        .balance-info p {
            font-size: 18px;
        }
        .withdrawal-info {
            margin-top: 30px;
            padding: 20px;
            background: var(--light);
            border-radius: 5px;
        }
        .withdrawal-info ul {
            padding-left: 20px;
            margin-top: 10px;
        }
        .withdrawal-info li {
            margin-bottom: 5px;
        }
        .referral-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        .referral-code {
            font-size: 24px;
            font-weight: bold;
            letter-spacing: 2px;
            color: var(--accent);
            margin: 15px 0;
            padding: 10px;
            background: var(--light);
            border-radius: 5px;
            text-align: center;
        }
        .share-link {
            display: flex;
            gap: 10px;
            margin: 20px 0;
        }
        .share-link input {
            flex: 1;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
        }
        .share-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        .share-buttons button {
            flex: 1;
            min-width: 150px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        table th, table td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        table th {
            background: var(--light);
            font-weight: 500;
        }
        table tr:hover {
            background: rgba(255, 215, 0, 0.1);
        }
        .error-container {
            max-width: 600px;
            margin: 50px auto;
            text-align: center;
        }
        .error-container h1 {
            font-size: 48px;
            margin-bottom: 20px;
            color: var(--danger);
        }
        .error-container p {
            font-size: 20px;
            margin-bottom: 30px;
        }
        @media (max-width: 768px) {
            .nav-links {
                display: none;
            }
            .quick-actions {
                flex-direction: column;
            }
            .share-buttons button {
                min-width: 100%;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <nav>
                <a href="{{ url_for('home') }}" class="logo">{{ site_name }}</a>
                {% if 'user_id' in session %}
                <div class="nav-links">
                    <a href="{{ url_for('dashboard') }}">Dashboard</a>
                    <a href="{{ url_for('invest') }}">Invest</a>
                    <a href="{{ url_for('withdraw') }}">Withdraw</a>
                    <a href="{{ url_for('referrals') }}">Referrals</a>
                </div>
                <div class="user-menu">
                    <span class="username">{{ session['username'] }}</span>
                    <a href="{{ url_for('logout') }}" class="btn btn-outline">Logout</a>
                </div>
                {% else %}
                <div class="nav-links">
                    <a href="#how-it-works">How It Works</a>
                    <a href="#plans">Plans</a>
                    <a href="#faq">FAQ</a>
                </div>
                <div class="auth-buttons">
                    <a href="{{ url_for('login') }}" class="btn btn-outline">Login</a>
                    <a href="{{ url_for('register') }}" class="btn btn-primary">Register</a>
                </div>
                {% endif %}
            </nav>
        </div>
    </header>

    <main>
        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            {% block content %}{% endblock %}
        </div>
    </main>

    <footer>
        <div class="container">
            <div class="footer-links">
                <a href="{{ url_for('home') }}">Home</a>
                <a href="#how-it-works">How It Works</a>
                <a href="#plans">Plans</a>
                <a href="#faq">FAQ</a>
                <a href="#">Contact</a>
                <a href="#">Terms</a>
                <a href="#">Privacy</a>
            </div>
            <div class="social-links">
                <a href="#"><i class="fab fa-facebook"></i></a>
                <a href="#"><i class="fab fa-twitter"></i></a>
                <a href="#"><i class="fab fa-instagram"></i></a>
                <a href="#"><i class="fab fa-telegram"></i></a>
            </div>
            <div class="contact-info">
                <p>Email: {{ support_email }} | Phone: {{ support_phone }}</p>
            </div>
            <p class="copyright">© {{ current_year }} {{ site_name }}. All rights reserved.</p>
        </div>
    </footer>

    <script>
        // Mobile menu toggle would be added in a real implementation
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Yellow Money Heist - Secure Investment Platform');
            
            // This would include more JavaScript functionality in a real implementation
            // Such as form validation, AJAX requests, etc.
        });
    </script>
</body>
</html>
        '''
    }
    
    return templates.get(template_name, '').format(**context)

# Initialize Database
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    # Schedule weekly payouts (in a real app, this would be a proper scheduler like Celery)
    from threading import Thread
    from time import sleep
    
    def payout_scheduler():
        while True:
            process_weekly_payouts()
            sleep(86400)  # Check daily
    
    scheduler_thread = Thread(target=payout_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    app.run(debug=True)
