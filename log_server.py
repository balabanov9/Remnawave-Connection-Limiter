"""HTTP server to receive logs from VPN nodes"""

from flask import Flask, request, jsonify
from database import log_connection, log_connections_batch, init_db
from config import LOG_SERVER_HOST, LOG_SERVER_PORT

app = Flask(__name__)


@app.route('/log', methods=['POST'])
def receive_log():
    """
    Endpoint для приема одного лога
    
    Expected JSON:
    {
        "user_email": "user_123",
        "ip_address": "1.2.3.4",
        "node_name": "node-1"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data'}), 400
        
        user_email = data.get('user_email')
        ip_address = data.get('ip_address')
        node_name = data.get('node_name', 'unknown')
        
        if not user_email or not ip_address:
            return jsonify({'error': 'Missing user_email or ip_address'}), 400
        
        log_connection(user_email, ip_address, node_name)
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        print(f"[ERROR] Log receive error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/log_batch', methods=['POST'])
def receive_log_batch():
    """
    Endpoint для приема пачки логов от ноды
    
    Expected JSON:
    {
        "connections": [
            {"user_email": "user_123", "ip_address": "1.2.3.4", "node_name": "node-1"},
            {"user_email": "user_456", "ip_address": "5.6.7.8", "node_name": "node-1"}
        ]
    }
    """
    try:
        data = request.get_json()
        
        if not data or 'connections' not in data:
            return jsonify({'error': 'No connections data'}), 400
        
        connections = data['connections']
        
        if not connections:
            return jsonify({'status': 'ok', 'count': 0}), 200
        
        # Валидация
        valid_connections = []
        for conn in connections:
            user_email = conn.get('user_email')
            ip_address = conn.get('ip_address')
            node_name = conn.get('node_name', 'unknown')
            
            if user_email and ip_address:
                valid_connections.append((user_email, ip_address, node_name))
        
        if valid_connections:
            log_connections_batch(valid_connections)
            print(f"[LOG] Received {len(valid_connections)} connections from {valid_connections[0][2]}")
        
        return jsonify({'status': 'ok', 'count': len(valid_connections)}), 200
        
    except Exception as e:
        print(f"[ERROR] Batch log receive error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200


def run_log_server():
    """Start the log collection server"""
    init_db()
    print(f"[INFO] Starting log server on {LOG_SERVER_HOST}:{LOG_SERVER_PORT}")
    app.run(host=LOG_SERVER_HOST, port=LOG_SERVER_PORT, threaded=True)


if __name__ == '__main__':
    run_log_server()
