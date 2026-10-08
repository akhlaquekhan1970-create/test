"""
app.py
──────
Slim Flask entry point. All route logic now lives in blueprints/ —
this file only:
  • creates the Flask app and its session/upload config
  • registers every blueprint
  • defines the two app-wide error handlers
  • runs the dev server

This replaces the original single-file IAD_flask.py (~7,700 lines).
See common.py for shared config/helpers used across blueprints.
"""
import os
import sys
from flask import Flask, jsonify

# Clear any existing Flask app state (kept from the original file)
import flask
flask.Flask._got_first_request = False

from common import (
    PROJECT_ROOT, TEMPLATE_FOLDER, PROJECT_PATH, UPLOAD_FOLDER,
    get_cfg, save_configuration, get_base_url,
)

print("=== FLASK APP CONFIGURATION ===")
print(f"Project root: {PROJECT_ROOT}")
print(f"Template folder path: {TEMPLATE_FOLDER}")
print(f"Template folder exists: {os.path.exists(TEMPLATE_FOLDER)}")

if os.path.exists(TEMPLATE_FOLDER):
    print(f"Files in templates folder: {os.listdir(TEMPLATE_FOLDER)}")
else:
    print("WARNING: Templates folder not found at expected location!")

# ── Create Flask app ─────────────────────────────────────────────
app = Flask(__name__, template_folder=TEMPLATE_FOLDER)
app.secret_key = 'bank+1234'

# Session configuration
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024 * 1024  # 512 MB — project ZIPs can be large

# ── Context processor to inject base_url into all templates ────
@app.context_processor
def inject_base_url():
    return {'base_url': get_base_url()}

# ── Register blueprints ──────────────────────────────────────────
# (import order doesn't matter functionally, but grouped to mirror
# the section order of the original monolithic file)
from blueprints.auth import auth_bp
from blueprints.pages import pages_bp
from blueprints.processing import processing_bp
from blueprints.archive import archive_bp
from blueprints.backup import backup_bp
from blueprints.restore import restore_bp
from blueprints.schema import schema_bp
from blueprints.modify import modify_bp
from blueprints.copy_files import copy_files_bp
from blueprints.order import order_bp
from blueprints.filtered_reports import filtered_reports_bp
from blueprints.pp_tables import pp_tables_bp
from blueprints.etl_files import etl_files_bp
from blueprints.review_files import review_files_bp
from blueprints.extraction import extraction_bp
from blueprints.reports import reports_bp
from blueprints.branch import branch_bp
from blueprints.transfer_files import transfer_files_bp

app.register_blueprint(auth_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(processing_bp)
app.register_blueprint(archive_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(restore_bp)
app.register_blueprint(schema_bp)
app.register_blueprint(modify_bp)
app.register_blueprint(copy_files_bp)
app.register_blueprint(order_bp)
app.register_blueprint(filtered_reports_bp)
app.register_blueprint(pp_tables_bp)
app.register_blueprint(etl_files_bp)
app.register_blueprint(review_files_bp)
app.register_blueprint(extraction_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(branch_bp)
app.register_blueprint(transfer_files_bp)


# ===== ERROR HANDLERS =====
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({
        'success': False,
        'error': 'Resource not found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error'
    }), 500


# ===== MAIN EXECUTION =====
if __name__ == '__main__':
    if not os.path.exists(TEMPLATE_FOLDER):
        print(f"Creating templates directory at: {TEMPLATE_FOLDER}")
        os.makedirs(TEMPLATE_FOLDER)

    config_path = os.path.join(PROJECT_ROOT, 'config.txt')
    if not os.path.exists(config_path):
        print("Creating default config file")
        # NOTE: app_URL / app_URL_VM are intentionally left blank here.
        # They must be supplied in config.txt — no IP is hard-coded in
        # this file. Edit config.txt after it's created to set them.
        default_config = {
            'drop_yes': 'Yes',
            'planning_path': 'D:\\project_files',
            'trunch_file': 'trunch_data.xlsx',
            'app_URL': '',
            'app_URL_VM': ''
        }
        save_configuration(default_config)

    # Get host from config — no hard-coded fallback IP. If it's missing
    # or blank, fail loudly instead of silently binding to some default.
    app_host = get_cfg('app_URL')
    app_host_vm = get_cfg('app_URL_VM')
    app_port = 5003

    if not app_host:
        print(f"ERROR: 'app_URL' is not set in {config_path}.")
        print("Please add an app_URL value (and app_URL_VM if needed) to config.txt and restart.")
        sys.exit(1)

    print("=== Starting Flask Server ===")
    print(f"Template folder: {TEMPLATE_FOLDER}")
    print(f"Project path: {PROJECT_PATH}")
    print(f"Server running on: http://{app_host}:{app_port}")
    print(f"URL from config: {app_host}")
    print(f"URL_VM from config: {app_host}")

    app.run(debug=True, port=app_port, host=app_host, threaded=True)
