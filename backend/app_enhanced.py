from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys
import json
import base64
import gc
import time
import requests
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import numpy as np
from typing import Dict

# 添加当前目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.data_manager import DataManager
from backend.kline_processor_enhanced import KLineProcessorEnhanced
from backend.trade_simulator_enhanced import TradeSimulatorEnhanced
from backend.user_manager_enhanced import UserManagerEnhanced
import backend.review_history as review_history

# 配置Flask以提供静态文件，支持开发环境和 PyInstaller 打包环境
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # 打包后环境
    frontend_folder = os.path.join(sys._MEIPASS, 'frontend')
else:
    # 开发环境
    frontend_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

app = Flask(__name__, static_folder=frontend_folder, static_url_path='/')
CORS(app)  # 允许跨域请求

# 获取项目根目录，确保路径在项目内
if getattr(sys, 'frozen', False):
    # project_root = os.path.dirname(sys.executable)
    project_root = os.path.join(os.path.dirname(sys.executable), '..')
else:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
users_dir_path = os.path.join(project_root, 'users')
data_dir_path = os.path.join(project_root, 'data')

# 初始化管理器
data_manager = DataManager(data_dir=data_dir_path)
# 股票列表缺失时在后台加载/下载，避免首个请求在请求线程里同步等待网络
data_manager.ensure_stock_list_async()
# user_manager = UserManager()
user_manager = UserManagerEnhanced(users_dir=users_dir_path)
active_trainings = {}  # 存储活跃的训练会话

@app.route('/')
def index():
    """提供前端入口页面"""
    return app.send_static_file('index_enhanced.html')


@app.route('/api/users', methods=['GET'])
def get_users():
    """获取用户列表"""
    try:
        users = user_manager.get_users()
        return jsonify(users)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users', methods=['POST'])
def create_user():
    """创建新用户"""
    try:
        data = request.get_json()
        username = data.get('username')
        
        if not username:
            return jsonify({'error': '用户名不能为空'}), 400
        
        if user_manager.user_exists(username):
            return jsonify({'error': '用户名已存在'}), 400
        
        user_manager.create_user(username)
        return jsonify({'message': '用户创建成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>', methods=['DELETE'])
def delete_user(username):
    """删除用户及其所有数据"""
    try:
        if not user_manager.user_exists(username):
            return jsonify({'error': '用户不存在'}), 404

        # 先丢弃该用户仍在内存里的训练会话，释放数据库句柄，否则 Windows 上删目录会被占用
        for training_id in [key for key, value in active_trainings.items() if value.get('user') == username]:
            active_trainings.pop(training_id, None)

        deleted = False
        for _ in range(3):
            if user_manager.delete_user(username):
                deleted = True
                break
            gc.collect()
            time.sleep(0.2)

        if deleted:
            return jsonify({'message': '用户删除成功'})
        return jsonify({'error': '删除用户失败：该用户的数据库仍被占用，请先结束训练或重启程序后再删'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/settings', methods=['GET'])
def get_user_settings(username):
    """获取用户设置"""
    try:
        config = user_manager.get_user_config(username)
        if config:
            return jsonify(config.get('settings', {}))
        else:
            return jsonify({'error': '用户不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/settings', methods=['POST'])
def update_user_settings(username):
    """更新用户设置"""
    try:
        data = request.get_json()
        config = user_manager.get_user_config(username)
        
        if not config:
            # 如果配置不存在，先创建默认配置，防止老用户数据丢失或缺失 config.json 导致无法保存
            user_manager.create_user(username)
            config = user_manager.get_user_config(username)
            if not config:
                return jsonify({'error': '用户不存在且创建配置失败'}), 404
        
        if 'settings' not in config:
            config['settings'] = {}
            
        # 更新设置
        config['settings'].update(data)
        
        if user_manager.update_user_config(username, config):
            return jsonify({'message': '设置更新成功'})
        else:
            return jsonify({'error': '设置更新失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/ai-review-prompt', methods=['GET'])
def get_ai_review_prompt_api(username):
    """读取当前 AI 复盘提示词：自定义内容 + 默认内容 + 实际生效内容"""
    try:
        config = user_manager.get_user_config(username)
        if not config:
            return jsonify({'error': '用户不存在'}), 404
        custom, default = get_ai_review_prompt(username)
        return jsonify({
            'prompt': custom,
            'effective': custom.strip() or default,
            'default_prompt': default,
            'is_custom': bool(custom.strip()),
            'max_length': AI_REVIEW_PROMPT_MAX_LEN,
            'placeholders': sorted(AI_PROMPT_PLACEHOLDERS.keys()),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/ai-review-prompt', methods=['PUT', 'POST'])
def update_ai_review_prompt_api(username):
    """保存 AI 复盘提示词；传空字符串表示恢复默认"""
    try:
        data = request.get_json(silent=True) or {}
        prompt = data.get('prompt', data.get('ai_review_prompt', ''))
        if prompt is None:
            prompt = ''
        if not isinstance(prompt, str):
            return jsonify({'error': 'prompt 必须是字符串'}), 400
        prompt = prompt.strip()
        if len(prompt) > AI_REVIEW_PROMPT_MAX_LEN:
            return jsonify({'error': f'提示词过长，最多 {AI_REVIEW_PROMPT_MAX_LEN} 字符'}), 400

        config = user_manager.get_user_config(username)
        if not config:
            user_manager.create_user(username)
            config = user_manager.get_user_config(username)
        if not config:
            return jsonify({'error': '用户不存在且创建配置失败'}), 404
        config.setdefault('settings', {})['ai_review_prompt'] = prompt
        if not user_manager.update_user_config(username, config):
            return jsonify({'error': '保存失败'}), 500

        return jsonify({
            'message': '提示词已保存' if prompt else '已恢复默认提示词',
            'prompt': prompt,
            'is_custom': bool(prompt),
            'effective': prompt or DEFAULT_AI_REVIEW_PROMPT,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/ai-review-prompt/reset', methods=['POST'])
def reset_ai_review_prompt_api(username):
    """恢复默认提示词（等价于 PUT 空字符串）"""
    try:
        config = user_manager.get_user_config(username)
        if not config:
            return jsonify({'error': '用户不存在'}), 404
        config.setdefault('settings', {})['ai_review_prompt'] = ''
        if not user_manager.update_user_config(username, config):
            return jsonify({'error': '保存失败'}), 500
        return jsonify({'message': '已恢复默认提示词', 'effective': DEFAULT_AI_REVIEW_PROMPT, 'is_custom': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/ai-review-issues', methods=['GET'])
def get_ai_review_issues_api(username):
    """读取历史问题档案（V2.1 机器协议回写的内容）"""
    try:
        config = user_manager.get_user_config(username)
        if not config:
            return jsonify({'error': '用户不存在'}), 404
        data = get_review_issues(username)
        return jsonify({
            'schema_version': data.get('schema_version', '1.0'),
            'updated_at': data.get('updated_at', ''),
            'count': len(data.get('issues') or []),
            'issues': data.get('issues') or [],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-history', methods=['GET'])
def list_review_history(username):
    """历史问题管理页的数据源：统计 + 筛选后的列表"""
    try:
        if not user_manager.get_user_config(username):
            return jsonify({'error': '用户不存在'}), 404
        archive = review_history.load(user_manager.users_dir, username)
        items = review_history.query(
            archive,
            category=request.args.get('category', ''),
            ai_status=request.args.get('ai_status', ''),
            user_status=request.args.get('user_status', ''),
            severity=request.args.get('severity', ''),
            keyword=request.args.get('q', ''),
        )
        return jsonify({
            'schema_version': archive.get('schema_version'),
            'updated_at': archive.get('updated_at', ''),
            'review_count': archive.get('review_count', 0),
            'summary': review_history.summary(archive),
            'issues': items,
            'filters': {
                'categories': list(review_history.CATEGORIES),
                'ai_statuses': list(review_history.AI_STATUSES),
                'user_statuses': list(review_history.USER_STATUSES),
                'severities': list(review_history.SEVERITIES),
            },
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-insights', methods=['GET'])
def review_insights(username):
    """能力画像 + 错题本：训练结果统计、历史问题分类聚合、规则对照违规汇总"""
    try:
        if not user_manager.get_user_config(username):
            return jsonify({'error': '用户不存在'}), 404

        history = user_manager.get_training_history(username, limit=200) or []
        finished = [h for h in history if h.get('has_report') or h.get('status') == 'completed']

        def _f(value, default=0.0):
            try:
                return float(value)
            except Exception:
                return default

        returns = [_f(h.get('total_return')) for h in finished if h.get('total_return') is not None]
        drawdowns = [_f(h.get('max_drawdown')) for h in finished if h.get('max_drawdown') is not None]
        trade_rates = [_f(h.get('trade_win_rate')) for h in finished if h.get('trade_win_rate') is not None]
        wins = sum(1 for r in returns if r > 0)
        profile = {
            'sessions': len(finished),
            'avg_return': round(sum(returns) / len(returns), 2) if returns else 0,
            'best_return': round(max(returns), 2) if returns else 0,
            'worst_return': round(min(returns), 2) if returns else 0,
            'win_sessions': wins,
            'session_win_rate': round(wins * 100 / len(returns), 1) if returns else 0,
            'avg_max_drawdown': round(sum(drawdowns) / len(drawdowns), 2) if drawdowns else 0,
            'avg_trade_win_rate': round(sum(trade_rates) / len(trade_rates), 1) if trade_rates else 0,
        }

        archive = review_history.load(user_manager.users_dir, username)
        issues = archive.get('issues') or []
        categories = {}
        active_status = ('待改进', '持续观察', '已改善')
        for issue in issues:
            cat = str(issue.get('category') or '其他')
            bucket = categories.setdefault(cat, {
                'category': cat, 'issue_count': 0, 'occurrences': 0, 'recurring': 0,
                'open_count': 0, 'resolved': 0, 'latest_seen': '', 'issues': [],
            })
            bucket['issue_count'] += 1
            bucket['occurrences'] += int(issue.get('occurrence_count') or 0)
            if issue.get('status_ai') == 'RECURRED':
                bucket['recurring'] += 1
            if issue.get('status_user') in active_status:
                bucket['open_count'] += 1
            if issue.get('status_user') == '已解决':
                bucket['resolved'] += 1
            last_seen = str(issue.get('last_seen') or '')
            if last_seen > bucket['latest_seen']:
                bucket['latest_seen'] = last_seen
            bucket['issues'].append({
                'issue_id': issue.get('issue_id'),
                'title': issue.get('title'),
                'severity': issue.get('severity'),
                'status_user': issue.get('status_user'),
                'status_ai': issue.get('status_ai'),
                'occurrence_count': int(issue.get('occurrence_count') or 0),
                'last_seen': last_seen,
                'recommended_rule': issue.get('recommended_rule') or '',
            })
        notebooks = []
        for bucket in categories.values():
            bucket['issues'] = sorted(
                bucket['issues'], key=lambda i: (-i['occurrence_count'], str(i.get('last_seen') or '')),
            )[:3]
            notebooks.append(bucket)
        notebooks.sort(key=lambda b: (-b['open_count'], -b['occurrences'], b['category']))

        rules = _user_trading_rules(username)
        rule_stats = {
            'configured': len(rules),
            'checks': 0, 'complied': 0, 'violated': 0, 'insufficient': 0, 'not_applicable': 0,
            'reports_with_checks': 0, 'compliance_rate': None, 'violations': [], 'by_rule': [],
        }
        per_rule = {}
        metas = user_manager.get_recent_review_meta(username, limit=60) or []
        for item in metas:
            meta = item.get('review_meta') or {}
            checks = meta.get('rule_check') or []
            if not checks:
                continue
            rule_stats['reports_with_checks'] += 1
            for check in checks:
                verdict = str(check.get('verdict') or 'INSUFFICIENT_DATA')
                rule_stats['checks'] += 1
                if verdict == 'COMPLIED':
                    rule_stats['complied'] += 1
                elif verdict == 'VIOLATED':
                    rule_stats['violated'] += 1
                    if len(rule_stats['violations']) < 12:
                        rule_stats['violations'].append({
                            'session_id': item.get('session_id'),
                            'updated_at': item.get('updated_at'),
                            'rule_id': check.get('rule_id'),
                            'rule': check.get('rule'),
                            'detail': check.get('detail'),
                            'evidence_fill_ids': check.get('evidence_fill_ids') or [],
                        })
                elif verdict == 'NOT_APPLICABLE':
                    rule_stats['not_applicable'] += 1
                else:
                    rule_stats['insufficient'] += 1
                key = str(check.get('rule_id') or '')
                row = per_rule.setdefault(key, {
                    'rule_id': key, 'rule': check.get('rule'), 'checks': 0,
                    'complied': 0, 'violated': 0, 'insufficient': 0, 'not_applicable': 0,
                })
                row['checks'] += 1
                if verdict == 'COMPLIED':
                    row['complied'] += 1
                elif verdict == 'VIOLATED':
                    row['violated'] += 1
                elif verdict == 'NOT_APPLICABLE':
                    row['not_applicable'] += 1
                else:
                    row['insufficient'] += 1
        decided = rule_stats['complied'] + rule_stats['violated']
        if decided:
            rule_stats['compliance_rate'] = round(rule_stats['complied'] * 100 / decided, 1)
        rule_stats['by_rule'] = sorted(per_rule.values(), key=lambda r: (-r['violated'], -r['checks']))

        return jsonify({
            'profile': profile,
            'notebook': {
                'total_issues': len(issues),
                'categories': notebooks,
            },
            'rules': {'items': rules, 'stats': rule_stats},
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-history/export', methods=['GET'])
def export_review_history(username):
    """导出 Markdown（阅读/交接用，JSON 仍是权威数据）"""
    try:
        archive = review_history.load(user_manager.users_dir, username)
        md = review_history.export_markdown(archive)
        return jsonify({'markdown': md, 'count': len(archive.get('issues') or [])})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-history/backups', methods=['GET'])
def list_review_history_backups(username):
    try:
        return jsonify({'backups': review_history.list_backups(user_manager.users_dir, username)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-history/backup', methods=['POST'])
def create_review_history_backup(username):
    try:
        name = review_history.backup(user_manager.users_dir, username)
        if not name:
            return jsonify({'error': '还没有历史问题档案可备份'}), 404
        return jsonify({'success': True, 'name': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-history/restore', methods=['POST'])
def restore_review_history(username):
    try:
        data = request.get_json() or {}
        ok, message = review_history.restore(user_manager.users_dir, username, str(data.get('name') or ''))
        if not ok:
            return jsonify({'error': message}), 400
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/review-history/<issue_id>', methods=['GET', 'PUT'])
def review_history_issue(username, issue_id):
    """查看单条问题 / 修改用户维护字段（描述、规则、备注、用户状态）"""
    try:
        if not user_manager.get_user_config(username):
            return jsonify({'error': '用户不存在'}), 404
        archive = review_history.load(user_manager.users_dir, username)
        issue = next((i for i in archive.get('issues') or [] if i.get('issue_id') == issue_id), None)
        if not issue:
            return jsonify({'error': '问题不存在'}), 404
        if request.method == 'GET':
            return jsonify({'issue': issue, 'user_statuses': list(review_history.USER_STATUSES)})

        payload = request.get_json() or {}
        fields = {k: payload.get(k) for k in review_history.USER_FIELDS if k in payload}
        ok, result = review_history.update_user_fields(user_manager.users_dir, username, issue_id, fields)
        if not ok:
            return jsonify({'error': result}), 400
        return jsonify({'success': True, 'changed': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/users/<username>/statistics', methods=['GET'])
def get_user_statistics(username):
    """获取用户统计信息"""
    try:
        stats = user_manager.get_user_statistics(username)
        if stats:
            return jsonify(stats)
        else:
            return jsonify({'error': '用户不存在'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _update_api_info(user=None, enable=None):
    """更新或删除 api_info.json"""
    if getattr(sys, 'frozen', False):
        api_file_path = os.path.join(os.path.dirname(sys.executable), '..', 'data', 'ai_api_info.json')
    else:
        api_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ai_api_info.json')
    
    if enable is None and user:
        user_config = user_manager.get_user_config(user)
        if user_config and 'settings' in user_config:
            enable = user_config['settings'].get('enable_ai_api', False)
        else:
            enable = False
            
    if not enable:
        if os.path.exists(api_file_path):
            try:
                os.remove(api_file_path)
            except Exception:
                pass
        return

    # 尝试获取base_url，如果不在请求上下文中可能为空
    try:
        base_url = request.host_url.rstrip('/') + "/api"
    except Exception:
        base_url = ""

    info = {
        "api_base_url": base_url,
        "active_trainings": list(active_trainings.keys()),
        "current_user": user,
        "endpoints": {
            "start_training": "POST /api/training/start",
            "next_bar": "POST /api/training/{training_id}/next",
            "execute_trade": "POST /api/training/{training_id}/trade",
            "adjustment": "POST /api/training/{training_id}/adjustment",
            "get_data": "GET /api/training/{training_id}/data",
            "get_account": "GET /api/training/{training_id}/account",
            "end_training": "POST /api/training/{training_id}/end"
        },
        "updated_at": datetime.now().isoformat()
    }
    
    try:
        with open(api_file_path, 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"写入 ai_api_info.json 失败: {e}")

def get_ai_config():
    if getattr(sys, 'frozen', False):
        config_file = os.path.join(os.path.dirname(sys.executable), '..', 'data', '.ai_tester_config.enc')
    else:
        config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', '.ai_tester_config.enc')
        
    if not os.path.exists(config_file):
        return None
    try:
        with open(config_file, 'r') as f:
            obfs = f.read().strip()
        if not obfs: return None
        key = "kline_trainer_secret_key"
        json_str = "".join(chr(ord(c) ^ ord(key[i % len(key)])) for i, c in enumerate(base64.b64decode(obfs).decode('utf-8')))
        return json.loads(json_str)
    except Exception as e:
        print(f"Failed to load AI config: {e}")
        return None

AI_CONFIG_NAME = '.ai_tester_config.enc'
AI_CONFIG_XOR_KEY = 'kline_trainer_secret_key'
DEFAULT_AI_BASE_URL = 'https://api.deepseek.com/v1'
DEFAULT_AI_MODEL = 'deepseek-chat'


def _ai_config_path() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), '..', 'data', AI_CONFIG_NAME)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', AI_CONFIG_NAME)


def save_ai_config(config: Dict) -> str:
    """把配置按主程序读取的格式写回加密文件（XOR + base64，与 set_ai_config.py 一致）"""
    path = _ai_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(config, ensure_ascii=False)
    obfs = "".join(chr(ord(c) ^ ord(AI_CONFIG_XOR_KEY[i % len(AI_CONFIG_XOR_KEY)])) for i, c in enumerate(text))
    payload = base64.b64encode(obfs.encode('utf-8')).decode('utf-8')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(payload)
    return path


def test_ai_connection(base_url, model, api_key) -> str:
    """用一次极小请求验证地址 / 模型 / Key；返回中文结论"""
    url = (base_url or '').rstrip('/') + '/chat/completions'
    try:
        resp = requests.post(
            url,
            headers={'Authorization': 'Bearer ' + (api_key or ''), 'Content-Type': 'application/json'},
            json={'model': model, 'messages': [{'role': 'user', 'content': '回复两个字：正常'}],
                  'max_tokens': 16, 'temperature': 0},
            timeout=30,
        )
    except Exception as exc:
        return '请求失败：%s' % exc
    if resp.status_code == 200:
        try:
            data = resp.json()
            reply = data['choices'][0]['message']['content'].strip()
            return '连通成功，模型回复：%s' % reply
        except Exception:
            return '返回 200，但响应结构不是 OpenAI 兼容格式，请检查地址'
    if resp.status_code == 401:
        return 'Key 无效或未开通（401）。地址与模型名本身是通的'
    return 'HTTP %d：%s' % (resp.status_code, resp.text[:200])

DEFAULT_COOLDOWN_BARS = 3


def get_cooldown_bars_setting(user) -> int:
    """读取用户设置中的「清仓后禁买期」交易日数，缺省为 3"""
    try:
        if not user:
            return DEFAULT_COOLDOWN_BARS
        config = user_manager.get_user_config(user)
        if not config:
            return DEFAULT_COOLDOWN_BARS
        value = config.get('settings', {}).get('cooldown_bars_after_flat', DEFAULT_COOLDOWN_BARS)
        return max(0, int(value))
    except Exception:
        return DEFAULT_COOLDOWN_BARS

def get_divergence_settings(user) -> Dict:
    """读取背离信号设置：show（是否显示，默认开）、pivot（拐点半宽，默认 3）、window（配对最大间隔，默认 60）"""
    result = {'show': True, 'pivot': 3, 'window': 60}
    try:
        if not user:
            return result
        config = user_manager.get_user_config(user) or {}
        settings = config.get('settings', {})
        if 'show_divergence_signals' in settings:
            result['show'] = bool(settings.get('show_divergence_signals'))
        if 'divergence_pivot' in settings:
            result['pivot'] = max(1, min(10, int(settings.get('divergence_pivot'))))
        if 'divergence_window' in settings:
            result['window'] = max(5, min(200, int(settings.get('divergence_window'))))
    except Exception:
        pass
    return result

def build_divergence_markers(kline_processor, training, view_period='daily'):
    """按用户设置计算背离信号标记，异常时返回空列表"""
    if view_period != 'daily':
        return []
    try:
        settings = get_divergence_settings(training.get('user'))
        if not settings['show']:
            return []
        return kline_processor.get_divergence_signals(
            view_period=view_period,
            pivot=settings['pivot'],
            window=settings['window'],
        )
    except Exception:
        return []

AI_REVIEW_SYSTEM_PROMPT = (
    "你是一位专业的量化和主观交易教练，擅长通过交易记录分析交易者的心理和策略问题。"
)

DEFAULT_AI_REVIEW_PROMPT = """A股 K线交易训练复盘专家 MASTER PROMPT V2.3（精简版 · 重点交易深评）

一、角色和任务
你是一位专业的 A 股量化与主观交易教练，负责审计交易者的买入、卖出、加仓、减仓行为，识别交易优势、重复错误和策略执行问题。
任务：根据真实成交记录、成交窗口 K 线、逐 Bar 持仓与资金快照、交易规则和历史问题档案，输出简洁、客观、有证据的复盘报告。
核心目标：
1. 找出真正创造收益的操作。
2. 找出损害收益最大的错误。
3. 分析买卖时机、交易节奏和仓位管理。
4. 判断历史问题是否再次出现、是否正在改善。
5. 提出下一阶段可直接执行和验证的改进规则。
始终区分交易结果与决策质量：盈利不代表操作正确，亏损不代表操作错误。

二、数据使用规则
1. 只使用本次实际传入的数据：账户信息、全部成交记录、成交窗口 K 线、逐 Bar 快照、策略规则、纪律检查、净值曲线特征、历史问题档案。
2. 不得假设没有传入的数据已被你看到，不得编造价格、成交量、Bar ID、技术指标或交易信号。
3. 所有判断必须区分「已确认事实」「基于数据的合理推测」「数据不足，无法判断」。
4. K线时间边界：买入决策只能使用成交时已经完成的 K 线和当时可获得的信息。成交所在 Bar 按当日收盘价成交，视为已完成。后 5 根 K 线只用于事后复盘，严禁把成交后的最高价、最低价、收盘价当作入场时已知信息。
5. 没有 OHLCV 时不得声称分析了真实 K 线形态；数据源未提供成交量，不得虚构量能判断。
6. 程序已计算现金、市值、均价、浮盈、累计已实现、仓位、回撤，不得重新推算基础数据，也不得因数字缺失而编造。
7. 不做佣金、印花税、交易成本分析；不自动引入大盘指数与行业指数；不修改用户原有买卖信号与参数。
8. 卖出与持仓评价只能使用「决策时点已经可见的信息」：成本、浮盈比例、仓位、持仓天数、当根及此前已完成的 K 线、当时既有的规则。卖出之后的价格走势属于事后信息，不得作为判断该笔卖出对错的依据。
9. 严格禁止结果论：卖出后继续上涨，不等于卖出错误；卖出后下跌，也不等于卖出正确。若报告中确实需要提到卖出后的走势，必须显式标注「事后信息，决策时不可知」，且不得据此加分或扣分。
10. 严格禁止双重标准：不得对同一类行为两头都批评。若用「没有让利润奔跑」批评提前止盈，就不能同时对持有回撤批评「没有及时止盈」；两者只能按同一套事先给定的卖出规则来判定，不能各用一套后验标准。
11. 判定「过早止盈 / 盈利回吐 / 延迟止损」等分类前，必须先引用当时的触发规则（止盈线、回撤阈值、减仓比例、信号失效条件等），再核对成交是否符合该规则。用户没有既定卖出规则时，只能写「缺少可执行的卖出规则」并建议建立规则，不得用事后最优路径反推当时的决策错误。
12. 评价句必须写成「依据当时的 X 信息，该操作是否遵守 Y 规则」；禁止「如果再多拿几天就……」「要是早点卖就……」这类后验假设式结论。

三、第一部分：总体印象
用 2—3 句话回答：本轮整体表现如何、最主要盈利来源、最大问题、是否存在收益依赖少数交易或盈利回吐。不要重复数字清单。

四、第二部分：做得好的地方（最多 2 项）
只保留最值得延续的动作，每项必须带日期、价格或 Bar ID 证据。优先检查：合理首次建仓、有效分批加仓、趋势持有、合理分批卖出、及时退出不利交易、稳定执行既有规则。

五、第三部分：核心问题（最多 3 项，按严重程度排序）
问题分类只能从以下 12 类中选：追涨买入、过早买入、亏损加仓、高位连续加仓、延迟止损、过早止盈、盈利回吐、反复交易、仓位过重、持仓管理不合理、策略执行不一致、其他。
每项写明：分类、具体交易证据（日期 + Bar + fill_id）、实际影响（金额或收益结构上的后果）。最多 3 项，不要罗列所有小毛病。

六、第四部分：交易纪律
严格使用【纪律检查】的结论。有违规：指出日期、Bar ID 和违反的具体规则；无违规：明确写「未发现违规」；无法判断：说明缺什么数据。
不得在没有盘中 K 线数据时判断止损或止盈已经触发。没违规不等于交易质量优秀。
另外逐条对照【用户交易规则】：只判断本轮成交是否遵守这条用户自定规则，不评价这条规则本身是否赚钱，也不做收益排名。
1. 每条规则只能给出「遵守 / 违反 / 无法判断 / 本轮未涉及」四种结论。
2. 判「违反」必须给出具体成交证据（日期 + Bar + fill_id）；没有证据就只能写「无法判断」。
3. 用户没有设置规则时，明确写「本轮没有可对照的交易规则」，不得临时发明规则，也不得用事后走势反推违规。
4. 规则对照只谈纪律执行，不得因为某一笔卖出之后涨了或跌了就改变结论。

七、第五部分：改进建议（最多 3 条）
每条包含：要改善的问题、历史交易证据、可直接执行的规则、可量化验证指标、可能副作用。
优先针对反复出现且影响最大的错误；缺少数据支持的建议标记为待验证假设。

八、第六部分：历史问题对照
档案见【历史问题档案】。
1. 如果没有历史问题，明确写「本轮为首次复盘」，不要虚构历史。
2. 如果有历史问题：逐项检查本轮成交是否再次出现、是否改善、证据是什么；没有相关场景的标「本轮未观察到」；证据不足的标「无法判断」。
3. 单轮未出现不等于已解决；盈利增加不等于习惯改善；亏损也不能直接推定旧问题复发。
4. 不得修改或覆盖用户的描述、备注与用户维护状态。

九、第七部分：双维度评分（两个分数独立，禁止合并）
A. 交易执行质量（100 分）：交易纪律 30、买入与建仓节奏 20、卖出与持仓管理 20、仓位与风险管理 20、执行一致性 10。
B. 收益表现（100 分）：净收益表现 25、最大回撤控制 25、盈亏结构 20、收益稳定性与盈利集中度 20、资金使用效率 10。
数据不足的维度标 N/A，并按有效权重重新计算；禁止编造分数；每个分数后用 2—4 句说明依据。

十、报告输出结构（必须严格遵守）
首页只输出以下 7 块，顺序固定：
一、总体印象
二、做得好的地方（最多 2 项）
三、核心问题（最多 3 项）
四、交易纪律
五、改进建议（最多 3 条）
六、历史问题对照
七、双维度评分
交易执行质量：XX/100
收益表现：XX/100

首页之后输出附录（软件会默认折叠，但内容必须完整）：
附录A 重点交易深度点评（0—3 笔）
只对值得研究的完整交易周期做深度点评，每笔固定 9 项：
1. 交易周期编号（trade_cycle_id）。
2. 首次建仓日期 → 最终清仓日期；未清仓写「期末仍持仓」。
3. 主要操作过程：按时间顺序写建仓、加仓、减仓、清仓的节奏，带 fill_id 与 Bar ID。
4. AI 总体评价：这个周期做对了什么、代价最大的问题是什么，2—3 句。
5. 主要优点：1—3 条，带证据。
6. 核心问题：1—3 条，带证据。
7. 经验总结：一条可以带走的原则。
8. 后续改进建议：1—3 条，可直接执行、可量化验证。
9. 证据成交：evidence_fill_ids，必须来自本轮成交表。
10. 卖出与持仓评价必须遵守第二部分的反结果论规则，不得用卖出之后的走势证明当时卖得对不对。
没有达到深评标准的周期时，明确写「本轮没有达到深评标准的交易周期」，不要凑数。
附录B 历史问题证据（可选，仅在确有对照结果时输出）
逐条列出问题 ID、观察结论、证据。

十一、重点交易选择标准（最多 3 笔，宁少勿多）
优先选择同时具备「完整周期 + 可学习结论」的交易：
1. 有代表性的错误操作（亏损加仓、追涨买入、延迟止损、盈利回吐等，且证据充分）。
2. 明显放大的风险暴露（仓位过重、连续加仓、单笔亏损占比高）。
3. 重大亏损，或值得复制的盈利交易（趋势持有、分批建仓与退出的节奏好）。
4. 重复出现的历史问题（与历史问题档案中的问题直接对应）。
5. 结构完整的周期（建仓 → 加仓或减仓 → 清仓可以完整还原）。
以下情况不得单独生成深度点评：小仓位试错、普通止盈、常规减仓、没有上下文的一笔孤立成交。
如果这些操作属于某个有研究价值的周期，就作为该周期「主要操作过程」里的事实证据写进去，不单独评论。
不得为了凑满 3 笔而选择普通交易：只有 1 笔值得写就只写 1 笔，没有就写没有。

十二、写作要求
简体中文；直接、简练、直击要害；首页正文控制在 600—900 字，不含附录。
不得写空洞表扬与免责声明；所有批评必须有证据；不得复述已展示的统计数字清单。
不要对每一笔成交单独点评：单笔操作只在附录A 的「主要操作过程」里作为事实出现。

十三、历史问题机器更新协议
报告正文结束后，输出一段机器可读 JSON，严格用以下标记包裹，标记之间只能是合法 JSON，不得有 Markdown 代码围栏或解释文字：
<<<TRADE_REVIEW_HISTORY_JSON>>>
{
  "schema_version": "1.0",
  "review_id": "本轮复盘编号",
  "key_trade_reviews": [
    {
      "trade_cycle_id": "C001",
      "title": "重点交易标题",
      "summary": "整周期总结",
      "strengths": ["优点"],
      "issues": ["问题"],
      "lesson": "交易经验（一条原则）",
      "next_rules": ["后续改进建议，可执行、可量化验证"],
      "evidence_fill_ids": ["F001", "F002"]
    }
  ],
  "history_updates": [
    {
      "target_issue_id": null,
      "operation": "CREATE",
      "category": "追涨买入",
      "title": "问题标题",
      "observation": "本轮观察到的具体行为与影响",
      "observation_status": "NEW",
      "severity": "HIGH",
      "confidence": "MEDIUM",
      "evidence": [
        {"symbol": "300557", "date": "2025-07-21", "bar_id": 671, "fill_id": "F012", "description": "实际交易证据"}
      ],
      "recommended_rule": "建议规则",
      "validation_metric": "如何验证",
      "rationale": "判断依据"
    }
  ],
  "rule_check": [
    {
      "rule_id": "R1",
      "verdict": "COMPLIED",
      "detail": "依据当时的仓位与止损线，本次清仓符合该条规则",
      "evidence_fill_ids": ["F003", "F004"]
    }
  ]
}
<<<END_TRADE_REVIEW_HISTORY_JSON>>>

协议规则：
1. operation 只能是 CREATE、UPDATE、NO_CHANGE。CREATE 用于新问题，target_issue_id 为 null；UPDATE 必须填档案中真实存在的 target_issue_id；NO_CHANGE 表示有观察但无需改动。
2. observation_status 只能是 NEW、RECURRED、IMPROVING、NOT_OBSERVED、INSUFFICIENT_DATA。
3. category 只能取上述 12 类之一；severity 与 confidence 只能取 HIGH、MEDIUM、LOW。
4. 没有新增问题时 history_updates 只放 UPDATE / NO_CHANGE 条目；完全没有可更新内容时输出空数组。
5. 不得编造 issue_id；不得删除问题；不得改动用户备注与用户维护状态（JSON 里没有这些字段）。
6. 同类问题优先 UPDATE 原记录，不重复创建；单次偶发且影响极小的问题不写入档案。
7. 不得把任何问题自动标记为「已解决」；「未观察到」不代表已解决。
8. 只输出软件可解析的 JSON，禁止文件路径、命令或任何文件系统操作要求。

9. 不再输出逐笔成交点评数组，也不要对单笔成交给 GOOD、NEUTRAL、NEEDS_ATTENTION 之类的评价或一句话短评。
10. key_trade_reviews 最多 3 笔，trade_cycle_id 必须使用成交表里的真实周期编号（C001 形式），不得虚构周期。
11. evidence_fill_ids 必须来自本轮真实成交（F001 形式），不得虚构；每笔重点交易尽量给 2—6 个关键证据成交，周期本身只有 1 笔时给 1 个。
12. 只写达到深评标准的周期；没有就输出空数组。不得为了凑满 3 笔把普通交易写成重点交易。
13. next_rules 给 1—3 条可执行、可量化验证的改进建议；没有就给空数组。
14. rule_check 必须逐条覆盖【用户交易规则】中的每条规则：rule_id 用 R1、R2…；verdict 只能是 COMPLIED、VIOLATED、INSUFFICIENT_DATA、NOT_APPLICABLE。
15. 判 VIOLATED 必须给出至少一个真实 evidence_fill_ids；证据不存在或不足时改判 INSUFFICIENT_DATA。
16. 没有配置用户规则时 rule_check 输出空数组，不要用默认规则代替用户规则。

现在开始读取数据并完成复盘。
"""

# 自定义提示词里可用的占位符，会被替换成本次训练的真实数值
def _num(value, ndigits=2):
    """把数字格式化成干净的小数文本，非数字原样返回"""
    try:
        return f"{round(float(value), ndigits):.{ndigits}f}"
    except Exception:
        return str(value if value is not None else '')


AI_PROMPT_PLACEHOLDERS = {
    'stock_code': lambda r: r.get('stock_code'),
    'start_date': lambda r: r.get('start_date'),
    'end_date': lambda r: r.get('end_date'),
    'initial_capital': lambda r: _num(r.get('initial_capital')),
    'final_capital': lambda r: _num(r.get('final_capital')),
    'total_return': lambda r: _num(r.get('total_return')),
    'max_drawdown': lambda r: _num(r.get('max_drawdown')),
    'total_trades': lambda r: r.get('total_trades'),
    'trade_win_rate': lambda r: _num(r.get('trade_win_rate')),
    'session_win_rate': lambda r: _num(r.get('session_win_rate')),
    'total_commission': lambda r: _num(r.get('total_commission')),
    'total_stamp_tax': lambda r: _num(r.get('total_stamp_tax')),
}

AI_REVIEW_PROMPT_MAX_LEN = 8000


def get_ai_review_prompt(username=None):
    """返回 (用户自定义提示词, 默认提示词)。自定义为空表示使用默认。"""
    custom = ''
    if username:
        try:
            config = user_manager.get_user_config(username) or {}
            custom = (config.get('settings') or {}).get('ai_review_prompt') or ''
        except Exception:
            custom = ''
    return str(custom), DEFAULT_AI_REVIEW_PROMPT


TRADING_RULES_MAX = 20
TRADING_RULE_MAX_LEN = 160
RULE_VERDICTS = ('COMPLIED', 'VIOLATED', 'INSUFFICIENT_DATA', 'NOT_APPLICABLE')
RULE_VERDICT_LABELS = {
    'COMPLIED': '遵守',
    'VIOLATED': '违反',
    'INSUFFICIENT_DATA': '无法判断',
    'NOT_APPLICABLE': '本轮未涉及',
}


def normalize_trading_rules(value):
    """把设置里的规则（数组或按行文本）整理成干净的规则列表"""
    if isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raw_items = str(value or '').splitlines()
    rules = []
    for item in raw_items:
        text = str(item or '').strip()
        for prefix in ('- ', '* ', '• ', '· '):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        text = text[:TRADING_RULE_MAX_LEN]
        if not text or text in rules:
            continue
        rules.append(text)
        if len(rules) >= TRADING_RULES_MAX:
            break
    return rules


def _user_trading_rules(username=None):
    """读取用户自定的交易规则（纪律一致性对照的基准）"""
    if not username:
        return []
    try:
        settings = (user_manager.get_user_config(username) or {}).get('settings') or {}
        return normalize_trading_rules(settings.get('trading_rules'))
    except Exception:
        return []


def build_user_rules_context(username=None) -> str:
    """把用户规则编号后交给模型，规则编号必须稳定可引用"""
    rules = _user_trading_rules(username)
    if not rules:
        return ('- 用户尚未设置交易规则。本轮只能提示「缺少可执行的规则」，'
                '不得用事后走势反推违规，也不得凭空发明规则。')
    lines = [f"- 共 {len(rules)} 条规则，规则编号仅供本轮 JSON 对照引用："]
    for idx, rule in enumerate(rules, start=1):
        lines.append(f"- R{idx}｜{rule}")
    return '\n'.join(lines)


def _review_settings(username=None) -> Dict:
    """取与本轮复盘相关的用户设置（禁买期、止损止盈）"""
    result = {'cooldown_bars_after_flat': DEFAULT_COOLDOWN_BARS, 'stop_loss_percent': 10, 'take_profit_percent': 20}
    if not username:
        return result
    try:
        config = user_manager.get_user_config(username) or {}
        settings = config.get('settings') or {}
        if 'cooldown_bars_after_flat' in settings:
            result['cooldown_bars_after_flat'] = max(0, int(settings.get('cooldown_bars_after_flat') or 0))
        if 'stop_loss_percent' in settings:
            result['stop_loss_percent'] = float(settings.get('stop_loss_percent') or 0)
        if 'take_profit_percent' in settings:
            result['take_profit_percent'] = float(settings.get('take_profit_percent') or 0)
    except Exception:
        pass
    return result


def build_discipline_check(report, settings) -> str:
    """按用户纪律规则检查交易流水：清仓后禁买期内是否又买入"""
    cooldown = int(settings.get('cooldown_bars_after_flat') or 0)
    trades = sorted(report.get('trade_details') or [], key=lambda t: int(t.get('bar_id') or 0))
    lines = []
    shares = 0
    cooldown_until = 0
    violations = []
    for t in trades:
        bar_id = int(t.get('bar_id') or 0)
        qty = int(t.get('quantity') or 0) * 100
        if t.get('action') == 'buy':
            if cooldown_until and bar_id <= cooldown_until:
                violations.append((t.get('date'), bar_id, cooldown_until))
            shares += qty
        elif t.get('action') == 'sell':
            shares -= qty
            if shares <= 0:
                shares = 0
                cooldown_until = bar_id + cooldown if cooldown else 0

    lines.append(f"- 清仓后禁买期设置：{cooldown} 个交易日（0 表示关闭）")
    if not cooldown:
        lines.append('- 本轮未启用禁买期规则，跳过该项检查')
    elif not violations:
        lines.append('- 未发现「清仓后禁买期内又买入」的违规')
    else:
        lines.append(f'- 发现 {len(violations)} 次禁买期违规：')
        for date, bar_id, until in violations:
            lines.append(f"  · {date}（Bar {bar_id}）在禁买期内买入，禁买期应到 Bar {until}")

    lines.append(
        f"- 成本线辅助设置：止损 -{settings.get('stop_loss_percent')}%、止盈 +{settings.get('take_profit_percent')}%"
        "（图上辅助线仅供参考，报告里不含盘中最低/最高，无法逐笔判定是否触碰）"
    )
    return '\n'.join(lines)


def _fmt_curve_time(value) -> str:
    """把净值曲线的时间统一成 YYYY-MM-DD（曲线的 time 可能是 unix 秒，也可能是日期字符串）"""
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value)).strftime('%Y-%m-%d')
        text = str(value or '')
        if text.isdigit() and len(text) >= 9:
            return datetime.fromtimestamp(float(text)).strftime('%Y-%m-%d')
        return text
    except Exception:
        return str(value)


def build_curve_context(report) -> str:
    """从净值曲线提取行情特征，供模型做收益归因"""
    curve = report.get('equity_curve') or []
    if len(curve) < 2:
        return '- 本轮没有净值曲线数据'
    lines = []
    size = len(curve)
    holding = sum(1 for p in curve if (p.get('position_shares') or 0) > 0)
    lines.append(f"- 净值曲线共 {size} 个点；有持仓的 K 线 {holding} 根（{round(holding * 100 / size, 1)}%），空仓 {size - holding} 根")
    lines.append(f"- 期末是否持仓：{'是' if (curve[-1].get('position_shares') or 0) > 0 else '否'}")

    # 最大回撤区间（按净值指数）
    peak = curve[0]
    worst = None
    for p in curve:
        idx = p.get('equity_index')
        if idx is None:
            continue
        if idx >= (peak.get('equity_index') or 0):
            peak = p
        else:
            depth = ((peak.get('equity_index') or 0) - idx) / (peak.get('equity_index') or 1) * 100
            if worst is None or depth > worst['depth']:
                worst = {'depth': depth, 'peak': peak, 'trough': p}
    if worst:
        lines.append(
            f"- 最大回撤 {round(worst['depth'], 2)}%：从 {_fmt_curve_time(worst['peak'].get('time'))} 的高点"
            f"回落到 {_fmt_curve_time(worst['trough'].get('time'))}"
        )

    # 单根涨跌最猛的区间
    best = None
    worst_bar = None
    for i in range(1, len(curve)):
        prev_idx = curve[i - 1].get('equity_index')
        cur_idx = curve[i].get('equity_index')
        if not prev_idx or cur_idx is None:
            continue
        change = (cur_idx - prev_idx) / prev_idx * 100
        if best is None or change > best['change']:
            best = {'change': change, 'time': curve[i].get('time')}
        if worst_bar is None or change < worst_bar['change']:
            worst_bar = {'change': change, 'time': curve[i].get('time')}
    if best:
        lines.append(f"- 净值单根涨幅最大：{_fmt_curve_time(best['time'])}，{round(best['change'], 2)}%")
    if worst_bar:
        lines.append(f"- 净值单根跌幅最大：{_fmt_curve_time(worst_bar['time'])}，{round(worst_bar['change'], 2)}%")
    return '\n'.join(lines)


HISTORY_JSON_START = '<<<TRADE_REVIEW_HISTORY_JSON>>>'
HISTORY_JSON_END = '<<<END_TRADE_REVIEW_HISTORY_JSON>>>'
DAILY_BAR_START = '09:30'
DAILY_BAR_END = '15:00'
AI_REVIEW_PROMPT_MAX_LEN = 8000
AI_REVIEW_MAX_CHARS = 110000
AI_REVIEW_MAX_FILLS = 150   # 单轮送模型的成交上限；超出取最早的 N 笔并在报告里披露


def get_review_issues(username) -> Dict:
    """读取历史问题档案（trade_review_history.json）"""
    if not username:
        return review_history.empty_archive('')
    return review_history.load(user_manager.users_dir, username)


def _issues_for_prompt(username) -> str:
    """只把未解决/观察中的问题传给模型"""
    if not username:
        return '[]'
    archive = review_history.load(user_manager.users_dir, username)
    payload = review_history.issues_for_prompt(archive)
    if not payload['issues']:
        return '[]（本轮首次复盘，暂无历史问题档案）'
    return json.dumps(payload, ensure_ascii=False)


def extract_review_history(text) -> tuple:
    """抽出机器 JSON 段，返回 (清理后的正文, dict 或 None)"""
    if not text:
        return text, None
    start = text.find(HISTORY_JSON_START)
    if start < 0:
        return text, None
    end = text.find(HISTORY_JSON_END, start)
    if end < 0:
        return text[:start].rstrip(), None
    raw = text[start + len(HISTORY_JSON_START):end].strip()
    clean = (text[:start] + text[end + len(HISTORY_JSON_END):]).strip()
    try:
        data = json.loads(raw)
    except Exception:
        return clean, None
    return clean, data if isinstance(data, dict) else None


def merge_review_history(username, payload, review_id='') -> str:
    """合并进档案；Schema 不合格时不改动原档案"""
    if not username or not isinstance(payload, dict):
        return ''
    result = review_history.apply_ai_updates(user_manager.users_dir, username, payload, review_id)
    if not result.get('valid'):
        print('历史问题 JSON 校验失败，已保留原档案：' + '；'.join(result.get('errors') or []))
        return '历史问题 JSON 校验失败，档案未改动'
    if result.get('errors'):
        print('历史问题合并跳过部分条目：' + '；'.join(result['errors']))
    return f"历史问题档案：新增 {result['created']} 条、更新 {result['updated']} 条、忽略 {result['ignored']} 条"


KEY_TRADE_MAX = 3


def _normalize_rule_check(payload, rules, by_id, errors):
    """校验 AI 返回的用户规则对照；规则编号必须对应本轮实际配置"""
    if not rules:
        if isinstance(payload, dict) and payload.get('rule_check') not in (None, []):
            errors.append('本轮没有配置用户规则，rule_check 已忽略')
        return []
    raw = payload.get('rule_check') if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        if raw is not None:
            errors.append('rule_check 不是数组，已忽略')
        return []
    known = {f'R{i}': rule for i, rule in enumerate(rules, start=1)}
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        rid = str(item.get('rule_id') or '').strip().upper()
        if rid not in known:
            errors.append(f'规则对照引用了不存在的规则编号：{rid or "(空)"}')
            continue
        if rid in seen:
            errors.append(f'规则 {rid} 重复对照，只保留第一条')
            continue
        verdict = str(item.get('verdict') or '').strip().upper()
        if verdict not in RULE_VERDICTS:
            errors.append(f'规则 {rid} 的 verdict 非法：{verdict or "(空)"}')
            continue
        evid = []
        if isinstance(item.get('evidence_fill_ids'), list):
            for fid in item['evidence_fill_ids']:
                fid = str(fid).strip()
                if fid in by_id:
                    evid.append(fid)
                else:
                    errors.append(f'规则 {rid} 的证据成交 {fid or "(空)"} 不存在，已剔除')
        if verdict == 'VIOLATED' and not evid:
            errors.append(f'规则 {rid} 判为违反但缺少有效证据成交，已降级为无法判断')
            verdict = 'INSUFFICIENT_DATA'
        seen.add(rid)
        out.append({
            'rule_id': rid,
            'rule': known[rid],
            'verdict': verdict,
            'detail': str(item.get('detail') or '').strip()[:240],
            'evidence_fill_ids': evid,
        })
    missing = [rid for rid in known if rid not in seen]
    if missing:
        errors.append('规则对照缺少：' + '、'.join(missing[:5]))
    return out


def validate_key_trade_reviews(report, payload, rules=None) -> Dict:
    """V2.3：只校验重点交易深度点评与用户规则对照，逐笔短评不再生成。

    fill_reviews 恒返回空数组（数据库里的旧逐笔点评继续保留，只是新报告不再产生）；
    key_trade_reviews 校验周期真实、证据成交真实、最多 KEY_TRADE_MAX 笔；
    rule_check 校验规则编号、结论与证据成交，最多覆盖本轮配置的规则条数。
    coverage 只披露本轮送模型的成交数、被 150 笔上限截掉的笔数与真实周期数。
    """
    rules = normalize_trading_rules(rules or [])
    mapping = build_fill_mapping(report, max_fills=AI_REVIEW_MAX_FILLS)
    fills = mapping['fills']
    by_id = {f['fill_id']: f for f in fills}
    errors = []
    cycles = {f['trade_cycle_id'] for f in fills if f.get('trade_cycle_id')}

    if not isinstance(payload, dict):
        errors.append('本轮回复没有可解析的机器 JSON，无法生成重点交易深度点评')
        return {
            'fill_reviews': [], 'key_trade_reviews': [], 'rule_check': [], 'errors': errors,
            'coverage': {'trades': len(fills), 'used_trades': len(fills),
                         'skipped_trades': mapping.get('skipped_trades', 0) or 0,
                         'cycles': len(cycles), 'key_trades': 0, 'rules': len(rules)},
        }

    raw_keys = payload.get('key_trade_reviews')
    keys = []
    if isinstance(raw_keys, list):
        cycle_seen = set()
        for item in raw_keys:
            if len(keys) >= KEY_TRADE_MAX:
                errors.append(f'重点交易超过 {KEY_TRADE_MAX} 笔，已截断')
                break
            if not isinstance(item, dict):
                continue
            cycle = str(item.get('trade_cycle_id') or '').strip()
            if cycle not in cycles:
                errors.append(f'跳过不存在的重点交易周期：{cycle or "(空)"}')
                continue
            if cycle in cycle_seen:
                errors.append(f'重点交易周期 {cycle} 重复，只保留第一条')
                continue
            cycle_seen.add(cycle)
            evid_fills = []
            if isinstance(item.get('evidence_fill_ids'), list):
                for fid in item['evidence_fill_ids']:
                    fid = str(fid).strip()
                    if fid in by_id:
                        evid_fills.append(fid)
                    else:
                        errors.append(f'重点交易 {cycle} 的证据成交 {fid or "(空)"} 不存在，已剔除')
            def _list_text(v, limit=3):
                if not isinstance(v, list):
                    return []
                return [str(x).strip()[:120] for x in v if str(x).strip()][:limit]
            keys.append({
                'trade_cycle_id': cycle,
                'title': str(item.get('title') or '').strip()[:40],
                'summary': str(item.get('summary') or '').strip()[:240],
                'strengths': _list_text(item.get('strengths')),
                'issues': _list_text(item.get('issues')),
                'lesson': str(item.get('lesson') or '').strip()[:240],
                'next_rules': _list_text(item.get('next_rules')),
                'evidence_fill_ids': evid_fills,
            })
    elif raw_keys is not None:
        errors.append('key_trade_reviews 不是数组，已忽略')

    rule_check = _normalize_rule_check(payload, rules, by_id, errors)

    return {
        'fill_reviews': [],   # V2.3：逐笔点评不再生成；历史报告的旧数据仍在数据库里，默认不展示
        'key_trade_reviews': keys,
        'rule_check': rule_check,
        'errors': errors,
        'coverage': {'trades': len(fills), 'used_trades': len(fills),
                     'skipped_trades': mapping.get('skipped_trades', 0) or 0,
                     'cycles': len(cycles), 'key_trades': len(keys), 'rules': len(rules)},
    }


# ---------------------------------------------------------------- 成交还原

def _bar_index(report) -> Dict:
    index = {}
    for row in report.get('kline_series') or []:
        try:
            index[int(row.get('bar_id'))] = row
        except Exception:
            continue
    return index


def _ohlc_text(row) -> str:
    if not row:
        return 'K线缺失'
    vol = row.get('volume')
    vol_text = f"V{_num(vol)}" if vol is not None else 'V缺失'
    return (f"O{_num(row.get('open'))} H{_num(row.get('high'))} "
            f"L{_num(row.get('low'))} C{_num(row.get('close'))} {vol_text}")


def _bar_ranges(bar_ids) -> str:
    """把 bar_id 列表压成区间串：10-16,18-22"""
    ids = sorted({int(b) for b in bar_ids if b})
    if not ids:
        return '无'
    parts = []
    start = prev = ids[0]
    for bid in ids[1:]:
        if bid == prev + 1:
            prev = bid
            continue
        parts.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = bid
    parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ','.join(parts)


def build_fill_mapping(report, max_fills=None) -> Dict:
    """把成交流水还原成带 fill_id / 交易周期 / 持仓变化的明细

    max_fills: 单轮送模型的成交上限；超出时只取最早的 N 笔（持仓前缀仍然正确），
    并在返回值里给出 total/used/skipped，供报告显式披露覆盖率。
    """
    bars = _bar_index(report)
    details = sorted(report.get('trade_details') or [], key=lambda t: int(t.get('bar_id') or 0))
    total_trades = len(details)
    used_details = details
    if max_fills and total_trades > max_fills:
        used_details = details[:max_fills]
    shares = 0
    avg_cost = 0.0
    realized = 0.0
    cycle = 0
    cycle_id = ''
    fills = []
    mapping_failed = []
    all_events = []

    for idx, t in enumerate(details, 1):
        keep = not max_fills or idx <= max_fills
        fill_id = f"F{idx:03d}" if keep else ''
        bar_id = int(t.get('bar_id') or 0)
        qty = int(t.get('quantity') or 0) * 100
        price = float(t.get('price') or 0)
        pos_before = shares

        if t.get('action') == 'buy':
            if pos_before == 0:
                cycle += 1
                cycle_id = f"C{cycle:03d}"
                action_type = '首次建仓' if cycle == 1 else '重新买入'
            else:
                action_type = '加仓'
            avg_cost = (avg_cost * pos_before + price * qty) / (pos_before + qty) if (pos_before + qty) else price
            shares += qty
        else:
            sold = min(qty, pos_before)
            realized += (price - avg_cost) * sold
            shares = max(0, pos_before - qty)
            action_type = '清仓' if shares == 0 else '减仓'
            if shares == 0:
                avg_cost = 0.0

        all_events.append({
            'bar_id': bar_id, 'side': t.get('action'),
            'price': price, 'quantity': int(t.get('quantity') or 0),
        })
        if not keep:
            continue

        mapped = bar_id in bars
        if not mapped:
            mapping_failed.append({'fill_id': fill_id, 'date': t.get('date'), 'bar_id': bar_id})
        wins = [bid for bid in range(bar_id - 10, bar_id + 6) if bid >= 1 and bid in bars]
        fills.append({
            'fill_id': fill_id,
            'bar_id': bar_id,
            'date': t.get('date'),
            'side': t.get('action'),
            'quantity': int(t.get('quantity') or 0),
            'price': price,
            'amount': t.get('amount'),
            'fee': round(float(t.get('commission') or 0) + float(t.get('stamp_tax') or 0), 2),
            'position_before': pos_before,
            'position_after': shares,
            'action_type': action_type,
            'trade_cycle_id': cycle_id,
            'mapping_status': 'OK' if mapped else 'MAPPING_FAILED',
            'window_bars': wins,
        })
    return {
        'fills': fills,
        'all_fills': all_events,
        'mapping_failed': mapping_failed,
        'cycles': cycle,
        'total_trades': total_trades,
        'used_trades': len(fills),
        'skipped_trades': total_trades - len(fills),
        'truncated': total_trades > len(fills),
        'max_fills': max_fills,
    }


def build_fill_context(report, mapping) -> str:
    """成交明细：逐笔带持仓变化、动作类型、Bar 时间边界、成交前后窗口"""
    fills = mapping['fills']
    total = mapping.get('total_trades', len(fills))
    used = len(fills)
    coverage = (used / total * 100) if total else 100.0
    first = f"- 原始成交记录：{total} 条；本次传入：{used} 条（覆盖率 {coverage:.2f}%）；" \
            f"可映射 Bar：{used - len(mapping['mapping_failed'])} 条；映射失败：{len(mapping['mapping_failed'])} 条；" \
            f"完整交易周期（全量统计）：{mapping['cycles']} 个"
    lines = [first]
    if mapping.get('truncated'):
        lines.append(
            f"- 已按单轮上限 {mapping.get('max_fills') or AI_REVIEW_MAX_FILLS} 笔截取最早的 {used} 笔；未覆盖 {mapping['skipped_trades']} 笔"
            f"（第 {used + 1} 笔及以后，仅计入周期与资金统计，不参与逐笔点评，也不得假装点评过）。"
        )
        lines.append(f"- 逐笔点评必须只针对 F001–F{used:03d}，并在报告里写明「本轮覆盖 {used}/{total} 笔」。")
    lines += [
        "- 成交方式：按当日收盘价成交，成交时该 Bar 已完成；T+1，当日买入当日不可卖",
        "- 时间边界：Bar 区间 09:30–15:00；「当根」= 成交 Bar；「前 10 根」为决策时已完成的 K 线；「后 5 根」只能用于事后复盘，禁止当作入场时已知信息",
        "- 窗口列格式：前 10 根 / 当根 / 后 5 根 中实际存在的 bar_id 区间，明细 OHLCV 见【成交窗口 K 线索引】",
        "- 配对口径：真实持仓变化还原；同一周期内按平均成本 + FIFO 作为分析约定，不代表券商原始批次",
        "",
        "| fill_id | Bar | 日期 | 方向 | 数量 | 价格 | 金额 | 费用 | 持仓变化 | 动作类型 | 周期 | 窗口 | Bar已完成 | 映射 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for f in fills:
        wins = _bar_ranges(f['window_bars'])
        lines.append(
            f"| {f['fill_id']} | {f['bar_id']} | {f['date']} | {f['side']} | {f['quantity']}手 | "
            f"{_num(f['price'])} | {_num(f['amount'])} | {f['fee']:.2f} | "
            f"{f['position_before']}→{f['position_after']}股 | {f['action_type']} | {f['trade_cycle_id']} | "
            f"{wins} | 是 | {f['mapping_status']} |"
        )
    if mapping['mapping_failed']:
        lines.append("")
        lines.append("- MAPPING_FAILED 明细（不得猜测附近 Bar）：")
        for m in mapping['mapping_failed']:
            lines.append(f"  · {m['fill_id']} {m['date']} 目标 Bar {m['bar_id']} 不在 K 线数据中")
    return '\n'.join(lines)


def build_kline_windows(report, mapping) -> str:
    """成交窗口 K 线索引：按 bar_id 去重，多笔共用同一段窗口只写一次"""
    bars = _bar_index(report)
    needed = set()
    for f in mapping['fills']:
        if f['mapping_status'] != 'OK':
            continue
        needed.update(f['window_bars'])
    if not needed:
        return '- 没有可用的 K 线窗口（成交 Bar 全部映射失败）'
    has_vol = sum(1 for bid in needed if bars.get(bid) and bars.get(bid).get('volume') is not None)
    head = (f"- 窗口 K 线索引，共 {len(needed)} 根（多笔成交共用窗口已去重）；"
            f"V 取自报告 kline_series 的 volume（单位沿用数据源）")
    if has_vol < len(needed):
        head += f"；其中 {len(needed) - has_vol} 根没有成交量（旧报告或数据源缺字段），这些根标记 V缺失"
    lines = [head]
    for bid in sorted(needed):
        row = bars.get(bid)
        lines.append(f"  Bar{bid} {_fmt_curve_time(row.get('time'))} {DAILY_BAR_START}-{DAILY_BAR_END} {_ohlc_text(row)}")
    return '\n'.join(lines)


def build_bar_snapshots(report, mapping, max_rows=1200) -> str:
    """逐 Bar 资金与持仓快照：现金、市值、均价、浮盈、累计已实现、仓位、回撤"""
    curve = report.get('equity_curve') or []
    if not curve:
        return '- 本轮没有逐 Bar 快照'
    total = len(curve)
    step = 1 if total <= max_rows else int(total / max_rows) + 1
    picked_ids = {int(p.get('bar_id') or 0) for p in curve[::step]}
    initial = float(report.get('initial_capital') or 0) or 1.0

    trades_by_bar = {}
    for f in (mapping.get('all_fills') or mapping['fills']):
        trades_by_bar.setdefault(f['bar_id'], []).append(f)

    shares = 0
    avg_cost = 0.0
    realized = 0.0
    peak = 0.0
    lines = [
        f"- 共 {total} 根 K 线；本次传入 {len(picked_ids)} 行" + (f"（每 {step} 根抽样 1 行）" if step > 1 else '（全部传入）'),
        '- 格式：Bar 日期 收盘 现金 持仓股 市值 均价 浮盈 累计已实现 总资产 仓位% 回撤%',
    ]

    for p in curve:
        bar_id = int(p.get('bar_id') or 0)
        for f in trades_by_bar.get(bar_id, []):
            qty = f['quantity'] * 100
            if f['side'] == 'buy':
                avg_cost = (avg_cost * shares + f['price'] * qty) / (shares + qty) if (shares + qty) else f['price']
            else:
                sold = min(qty, shares)
                realized += (f['price'] - avg_cost) * sold
                if shares - qty <= 0:
                    avg_cost = 0.0

        shares = int(p.get('position_shares') or 0)
        close = float(p.get('close') or 0)
        equity = p.get('equity')
        if equity is None:
            equity = (float(p.get('equity_index') or 0) / 100.0) * initial
        cash = p.get('cash')
        if cash is None:
            cash = float(equity) - shares * close
        mv = shares * close
        unrealized = (close - avg_cost) * shares if shares else 0.0
        weight = (mv / equity * 100) if equity else 0.0
        peak = max(peak, float(equity))
        dd = ((float(equity) - peak) / peak * 100) if peak else 0.0

        if bar_id not in picked_ids:
            continue
        lines.append(
            f"  Bar{bar_id} {_fmt_curve_time(p.get('time'))} C{_num(close)} 现{_num(cash)} "
            f"持{shares} 值{_num(mv)} 均{_num(avg_cost)} 浮{_num(unrealized)} "
            f"实{_num(realized)} 总{_num(equity)} 仓{round(weight, 1)}% 回{round(dd, 2)}%"
        )
    return '\n'.join(lines)


def build_strategy_rules(username) -> str:
    """把现有交易规则原样交给模型"""
    s = _review_settings(username)
    return '\n'.join([
        f"- 清仓后禁买期：{s.get('cooldown_bars_after_flat')} 个交易日（0 表示关闭）",
        f"- 止损线：成本价 -{s.get('stop_loss_percent')}%",
        f"- 止盈线：成本价 +{s.get('take_profit_percent')}%",
        "- 下单方式：按可用资金/可卖持仓的百分比折算手数（100% = 满仓买入 / 全部卖光，11 档：0%、10%…100%）",
        "- 成交方式：按当日收盘价成交，T+1（当日买入不可卖）",
        "- 以上为现有规则原文，不得自行修改参数或新增买卖信号",
    ])


# ---------------------------------------------------------------- 报告导出

def _md_cell(value) -> str:
    """表格单元格转义：竖线与换行会破坏 Markdown 表格"""
    if value is None:
        return '—'
    text = str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')
    return text if text else '—'


def _md_join(items) -> str:
    if not items:
        return '—'
    return '；'.join(str(i) for i in items)


def _demote_markdown_headings(text) -> str:
    """AI 原文的标题整体降两级，避免与导出文档自己的目录混在一起"""
    if not text:
        return ''
    out = []
    for line in str(text).splitlines():
        out.append('##' + line if line.lstrip().startswith('#') else line)
    return '\n'.join(out)


def build_report_export_markdown(username, session_id, session, report, ai_analysis, review_meta=None, issues=None):
    """导出单期复盘的 Markdown 数据包

    内容＝该轮 AI 复盘实际用到的全部数据（成交流水、成交窗口 K 线、逐 Bar 资金快照、
    重点交易、历史问题档案）＋ AI 复盘原文，便于拿到外部讨论交易规则。
    """
    report = report or {}
    session = session or {}
    review_meta = review_meta or {}
    bars = _bar_index(report)
    curve = report.get('equity_curve') or []
    mapping = build_fill_mapping(report)
    stock_name = report.get('stock_name') or session.get('stock_name') or '—'
    stock_code = report.get('stock_code') or session.get('stock_code') or '—'
    if stock_code != '—' and stock_name == f'股票{stock_code}':
        stock_name = stock_code  # 数据源把名称写成「股票300557」，导出时去掉重复
    initial = float(report.get('initial_capital') or 0)
    final_capital = report.get('final_capital')
    total_return = report.get('total_return')
    max_dd = report.get('max_drawdown')
    total_trades = report.get('total_trades') or mapping.get('total_trades') or 0
    sell_trades = report.get('total_sell_trades')
    win_count = report.get('win_count')
    win_rate = report.get('session_win_rate')
    if win_rate is None:
        win_rate = report.get('trade_win_rate')
    win_rate_calc = (win_count / sell_trades * 100) if (win_count and sell_trades) else None
    commission = float(report.get('total_commission') or 0)
    stamp_tax = float(report.get('total_stamp_tax') or 0)
    commission_settings = report.get('commission_settings') or {}
    review_coverage = review_meta.get('coverage') or {}
    model = review_meta.get('model') or session.get('ai_model')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        f'# {stock_name if stock_name != stock_code else stock_code} 交易复盘数据包',
        '',
        f'> 导出时间：{now}　用户：{username}　会话：{session_id}',
        f'> 本文件包含该轮 AI 复盘实际读取的全部数据与 AI 复盘原文，用于在外部讨论买卖规则、仓位与卖出标准。',
        '',
        '## 一、训练概况',
        '',
        '| 项目 | 内容 |',
        '| --- | --- |',
        f'| 会话 ID | {_md_cell(session_id)} |',
        f'| 股票 | {_md_cell(stock_code if stock_name == stock_code else f"{stock_name}（{stock_code}）")} |',
        f'| 区间 | {_md_cell(report.get("start_date") or session.get("start_date"))} → {_md_cell(report.get("end_date") or session.get("end_date"))} |',
        f'| K 线根数 | {len(bars)} |',
        f'| 成交笔数 | {total_trades} |',
        f'| 完整交易周期 | {mapping.get("cycles", 0)} 个 |',
        f'| 复盘模型 | {_md_cell(model)} |',
        f'| 复盘覆盖 | {review_coverage.get("used_trades", "—")} / {review_coverage.get("trades", total_trades)} 笔，重点交易 {review_coverage.get("key_trades", 0)} 笔 |',
        '',
        '## 二、核心指标',
        '',
        '| 指标 | 数值 |',
        '| --- | --- |',
        f'| 初始资金 | {_num(initial)} |',
        f'| 期末资产 | {_num(final_capital)} |',
        f'| 总收益率 | {_num(total_return)}% |',
        f'| 最大回撤 | {_num(max_dd)}% |',
        f'| 成交笔数（买+卖） | {total_trades} |',
        f'| 卖出笔数 | {_md_cell(sell_trades)} |',
        f'| 盈利卖出笔数 | {_md_cell(win_count)} |',
        f'| 胜率（盈利卖出 / 卖出笔数） | {f"{win_rate_calc:.2f}%" if win_rate_calc is not None else "—"} |',
        f'| 报告记录的胜率字段 | {_num(win_rate)}% |',
        f'| 总佣金 | {_num(commission)} |',
        f'| 总印花税 | {_num(stamp_tax)} |',
        f'| 费用合计 | {_num(commission + stamp_tax)} |',
        '',
        '## 三、行情与资金逐 Bar 全量（AI 判断的原始数据）',
        '',
        f'共 {len(curve)} 个 Bar；净值指数以起始资金 100 为基准。成交量缺失时标「—」。',
        '',
        '| Bar | 日期 | 开 | 高 | 低 | 收 | 量 | 净值 | 收益率% | 持仓股 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for point in curve:
        bar_id = int(point.get('bar_id') or 0)
        bar = bars.get(bar_id) or {}
        vol = bar.get('volume')
        lines.append(
            f'| {bar_id} | {_fmt_curve_time(point.get("time") or bar.get("time"))} '
            f'| {_num(bar.get("open"))} | {_num(bar.get("high"))} | {_num(bar.get("low"))} '
            f'| {_num(point.get("close") if point.get("close") is not None else bar.get("close"))} '
            f'| {_md_cell(vol if vol is not None else "—")} '
            f'| {_num(point.get("equity_index"))} | {_num(point.get("return_pct"))} '
            f'| {int(point.get("position_shares") or 0)} |'
        )

    lines += [
        '',
        '## 四、成交明细（全量，含持仓变化与交易周期）',
        '',
        f'- 原始成交 {mapping.get("total_trades", 0)} 笔；导出 {mapping.get("used_trades", 0)} 笔'
        + ('（导出不做截断，全量列出）' if not mapping.get('truncated') else f'（有 {mapping.get("skipped_trades", 0)} 笔未进入逐笔表）'),
        '- 口径：按当日收盘价成交，T+1；持仓变化由真实成交还原；周期按空仓→建仓→清仓划分。',
        '',
        '| fill_id | Bar | 日期 | 方向 | 手数 | 价格 | 金额 | 费用 | 持仓变化 | 动作类型 | 周期 | 映射 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for fill in mapping['fills']:
        lines.append(
            f'| {fill["fill_id"]} | {fill["bar_id"]} | {_md_cell(fill.get("date"))} | {fill["side"]} '
            f'| {fill["quantity"]} | {_num(fill["price"])} | {_num(fill.get("amount"))} '
            f'| {fill["fee"]:.2f} | {fill["position_before"]}→{fill["position_after"]}股 '
            f'| {fill["action_type"]} | {fill["trade_cycle_id"]} | {fill["mapping_status"]} |'
        )
    if not mapping['fills']:
        origin = report.get('trade_details') or []
        for idx, t in enumerate(origin, 1):
            lines.append(
                f'| F{idx:03d} | {_md_cell(t.get("bar_id"))} | {_md_cell(t.get("date"))} | {_md_cell(t.get("action"))} '
                f'| {_md_cell(t.get("quantity"))} | {_num(t.get("price"))} | {_num(t.get("amount"))} | — | — | — | — | — |'
            )

    lines += [
        '',
        '## 五、成交窗口 K 线（AI 实际读取的那份）',
        '',
        '```text',
        build_kline_windows(report, mapping),
        '```',
        '',
        '## 六、逐 Bar 资金与持仓快照（AI 实际读取的那份）',
        '',
        '```text',
        build_bar_snapshots(report, mapping, max_rows=len(curve) + 1 if curve else 1200),
        '```',
        '',
        '## 七、重点交易深度点评（最多 3 笔）',
        '',
    ]
    key_trades = review_meta.get('key_trade_reviews') or []
    if key_trades:
        for idx, item in enumerate(key_trades, 1):
            lines += [
                f'### {idx}. {_md_cell(item.get("trade_cycle_id"))} {_md_cell(item.get("title"))}',
                '',
                f'- 交易周期：{_md_cell(item.get("trade_cycle_id"))}',
                f'- 概述：{_md_cell(item.get("summary"))}',
                f'- 主要优点：{_md_cell(_md_join(item.get("strengths")))}',
                f'- 核心问题：{_md_cell(_md_join(item.get("issues")))}',
                f'- 经验总结：{_md_cell(item.get("lesson"))}',
                f'- 后续改进：{_md_cell(_md_join(item.get("next_rules")))}',
                f'- 证据成交：{_md_cell(_md_join(item.get("evidence_fill_ids")))}',
                '',
            ]
    else:
        lines += ['- 本轮没有保存重点交易点评。', '']

    lines += ['## 八、历史问题档案（导出时快照）', '']
    issue_list = issues or []
    if issue_list:
        lines += [
            '| 问题 ID | 状态 | 问题描述 | 建议规则 | 用户备注 |',
            '| --- | --- | --- | --- | --- |',
        ]
        for issue in issue_list:
            lines.append(
                f'| {_md_cell(issue.get("id"))} | {_md_cell(issue.get("status_user") or issue.get("status"))} '
                f'| {_md_cell(issue.get("description"))} | {_md_cell(issue.get("recommended_rule"))} '
                f'| {_md_cell(issue.get("user_note"))} |'
            )
    else:
        lines.append('- 该用户还没有历史问题档案（本轮可能是首次复盘）。')

    rules_snapshot = normalize_trading_rules(_user_trading_rules(username))
    rule_checks = review_meta.get('rule_check') or []
    lines += ['', '## 九、交易规则与纪律对照（导出时快照）', '']
    if rules_snapshot:
        lines.append('- 本轮配置的交易规则：')
        for idx, rule in enumerate(rules_snapshot, start=1):
            lines.append(f'  - R{idx}｜{rule}')
    else:
        lines.append('- 本轮没有配置交易规则，无法做规则一致性对照。')
    if rule_checks:
        lines += ['', '| 规则 | 结论 | 说明 | 证据成交 |', '| --- | --- | --- | --- |']
        for check in rule_checks:
            verdict = RULE_VERDICT_LABELS.get(str(check.get('verdict')), str(check.get('verdict') or '—'))
            lines.append(
                f'| {_md_cell(check.get("rule_id"))} {_md_cell(check.get("rule"))} | {verdict} '
                f'| {_md_cell(check.get("detail"))} | {_md_cell(_md_join(check.get("evidence_fill_ids")))} |'
            )
    elif rules_snapshot:
        lines.append('- 本轮 AI 没有返回规则对照结果（可能未开启 AI 复盘或模型输出缺少 rule_check）。')

    lines += [
        '',
        '## 十、AI 复盘原文',
        '',
        (_demote_markdown_headings(ai_analysis) or '- 本轮没有 AI 复盘原文（可能未开启 AI 分析或接口失败）。'),        '',
        '## 十一、口径与说明',
        '',
        f'- 成交价：当日收盘价；T+1（当日买入当日不可卖）。',
        f'- 费用设置：佣金率 {commission_settings.get("commission_rate", "—")}、最低佣金 {commission_settings.get("min_commission", "—")}、印花税率 {commission_settings.get("stamp_tax_rate", "—")}。',
        '- 成本与配对：按真实持仓变化还原，同一周期内用平均成本 + FIFO 作为分析约定，不代表券商原始批次。',
        '- 评分体系：交易执行质量与收益表现两个维度独立打分，禁止合并成一个总分。',
        '- 卖出评价口径：只按决策当时可见的信息（成本、浮盈、仓位、已完成 K 线、既定规则）判断；卖出之后的走势属于事后信息，不参与对错评判，也不允许对「提前止盈」与「持有回撤」使用两套相反标准。',
        '',
        f'*数据来源：用户 {username} 的本地训练库 session {session_id}（report_json + ai_analysis + review_meta）。*',
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------------- 提示词组装

RULE_CHECK_APPENDIX = """
【用户交易规则对照附加协议】
1. 必须逐条对照【用户交易规则（纪律对照基准）】中的每条规则，只判断本轮成交是否遵守，不评价规则本身的盈亏，不做收益排名。
2. 在复盘 JSON 的顶层额外输出 rule_check 数组：{"rule_id":"R1","verdict":"COMPLIED|VIOLATED|INSUFFICIENT_DATA|NOT_APPLICABLE","detail":"依据当时可见信息的判断","evidence_fill_ids":["F001"]}。
3. VIOLATED 必须给出至少一个真实 evidence_fill_ids；证据不足或不存在时只能写 INSUFFICIENT_DATA。
4. 不得用卖出之后的走势反推违规；没有配置规则时 rule_check 输出空数组。
"""


def build_ai_review_messages(report, username=None):
    """组装 AI 复盘 messages：程序算好数据，模型只做判断"""
    custom_prompt, default_prompt = get_ai_review_prompt(username)
    requirements = custom_prompt.strip() or default_prompt
    if custom_prompt.strip() and _user_trading_rules(username):
        # 自定义提示词可能是旧版协议：补一段最小规则对照契约，避免规则发了但模型不返回结果
        requirements = requirements.rstrip() + '\n' + RULE_CHECK_APPENDIX
    requirements = requirements.replace('{historical_issues}', '见下方【历史问题档案】')
    for key, getter in AI_PROMPT_PLACEHOLDERS.items():
        try:
            value = getter(report)
        except Exception:
            value = ''
        requirements = requirements.replace('{' + key + '}', str(value))

    issues_text = _issues_for_prompt(username)

    def _assemble(max_fills):
        mapping = build_fill_mapping(report, max_fills=max_fills)
        lines = [
            "请严格按【复盘要求】中的模板完成本轮 A 股 K 线训练复盘。数据不足的部分按模板标记为「无法判断」，不要编造。",
            "",
            "【训练基本信息】",
            f"- 股票代码: {report.get('stock_code')}（{report.get('stock_name') or ''}）",
            f"- 训练期间: {report.get('start_date')} 至 {report.get('end_date')}",
            f"- 初始资金: {_num(report.get('initial_capital'))}",
            f"- 最终资金: {_num(report.get('final_capital'))}",
            f"- 总收益率: {_num(report.get('total_return'))}%",
            f"- 最大回撤: {_num(report.get('max_drawdown', 0))}%",
            f"- 总交易次数: {report.get('total_trades')}",
            f"- 交易胜率（按卖出笔数）: {_num(report.get('trade_win_rate'))}%",
            f"- 局胜率（整轮盈亏）: {_num(report.get('session_win_rate'))}%",
            f"- 盈利卖出笔数 / 总卖出笔数: {report.get('win_count')} / {report.get('total_sell_trades')}",
            "",
            "【策略与纪律规则】",
            build_strategy_rules(username),
            "",
            "【用户交易规则（纪律对照基准）】",
            build_user_rules_context(username),
            "",
            "【成交记录与持仓还原】",
            build_fill_context(report, mapping),
            "",
            "【成交窗口 K 线索引】",
            build_kline_windows(report, mapping),
            "",
            "【逐 Bar 资金与持仓快照】",
            build_bar_snapshots(report, mapping),
            "",
            "【纪律检查】",
            build_discipline_check(report, _review_settings(username)),
            "",
            "【净值曲线特征】",
            build_curve_context(report),
            "",
            "【历史问题档案】",
            issues_text,
            "",
            "【复盘要求】",
            requirements,
        ]
        content = '\n'.join([ln for ln in lines if ln is not None])
        return content.replace('\n\n\n', '\n\n'), mapping

    # 先按 150 笔组装；若仍超长，自动把成交上限减半再试，直到够短或已缩到 15 笔
    limit = AI_REVIEW_MAX_FILLS
    content, mapping = _assemble(limit)
    shrink_trace = []
    while len(content) > AI_REVIEW_MAX_CHARS and mapping['used_trades'] > 15:
        limit = max(15, mapping['used_trades'] // 2)
        content, mapping = _assemble(limit)
        shrink_trace.append(limit)
    if len(content) > AI_REVIEW_MAX_CHARS:
        trace_text = f"（已自动把成交上限从 {AI_REVIEW_MAX_FILLS} 笔缩减到 {mapping['used_trades']} 笔仍超长）" if shrink_trace else ''
        raise ValueError(
            f"本轮数据约 {len(content)} 字符，超过单次请求上限 {AI_REVIEW_MAX_CHARS}{trace_text}。"
            "为避免生成遗漏成交的伪完整报告，未发起模型调用；请缩短训练区间或拆分训练后再复盘。"
        )
    return [
        {"role": "system", "content": AI_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def analyze_report_with_ai(report, username=None):
    """返回 (正文, 结构化点评)；结构化点评始终是 dict，供前端曲线消费"""
    ai_config = get_ai_config()
    if not ai_config:
        return "AI 配置未找到，请在 AI 测试器中配置。", None

    base_url = ai_config.get("base_url", "https://api.openai.com/v1").rstrip('/')
    api_key = ai_config.get("api_key", "")
    model = ai_config.get("model", "gpt-3.5-turbo")

    if not api_key:
        return "AI API Key 未配置，无法进行分析。", None

    try:
        messages = build_ai_review_messages(report, username)
    except ValueError as e:
        return str(e), None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7
    }

    try:
        response = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=120)
        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content']
            clean, history = extract_review_history(content)
            if history:
                summary = merge_review_history(username, history, report.get('session_id') or '')
                if summary:
                    print(summary)
            structured = validate_key_trade_reviews(report, history, rules=_user_trading_rules(username))
            if structured['errors']:
                print('结构化点评校验提示：' + '；'.join(structured['errors'][:6]))
            structured['review_id'] = report.get('session_id') or ''
            structured['model'] = model
            return clean, structured
        else:
            return f"AI API请求失败: {response.status_code} {response.text}", None
    except Exception as e:
        return f"AI 分析请求发生错误: {str(e)}", None


# ---------------------------------------------------------------- AI 实时陪练

AI_COACH_SYSTEM_PROMPT = """A股 K线复盘训练器 · 实时陪练（MASTER PROMPT V2.4 陪练版）

一、角色
你是用户在做 K 线复盘训练时的陪练教练。用户每推进一步都会看到新的 K 线，你可以基于「已经发生的行情」帮他理解结构、指标、仓位与规则，但你没有预测能力，也不替用户下单。

二、数据边界（最高优先级）
1. 只使用本轮消息里给出的【当前状态】【最近 K 线】【技术指标】【持仓与成交】【交易规则】。没有给出的数据一律不得假设、不得编造。
2. 你看到的数据截止到当前 Bar（已收盘）。之后的走势对你和用户都未知：禁止推断、暗示、描述「后面会怎么走」，禁止出现「接下来大概率会……」「明天会……」这类表述。
3. 不预测具体价格、点位、涨跌幅和转折时间；不声称某个位置「一定会」或「不可能」。
4. 不得虚构价格、Bar ID、指标数值、成交量、新闻或基本面消息。
5. 若用户要求预测，直接说明「训练器不提供未来数据，我只能讲当前结构的含义和条件式应对」，然后给出条件式分析。

三、回答口径
1. 分开写清：已确认事实（数据里能直接读到的）、推断（有条件的假设）、不确定（缺什么数据）。
2. 用户问「该不该买 / 卖 / 加仓」时，不要直接下指令。先给当前结构判断（趋势位置、量能、指标状态、仓位与成本），再列支持理由与反对理由，给出触发条件和失效条件，最后明确「决定权在你」。
3. 禁止结果论：不得用「后来涨了/跌了」评价用户之前的操作，也不得暗示「你刚才本该如何」。评价只基于当时可见的信息和既定规则。
4. 讨论仓位时必须结合：可用现金、持仓股数、平均成本、浮盈比例、止损止盈规则、禁买期状态。空仓时说明这是新开仓问题。
5. 数据不足就直说缺什么（例如没有分时、没有板块数据），不要用常识补。
6. 简洁：中文，先结论后依据，总字数控制在 300 字以内；不复述整张数据表。
7. 用户连续追问时沿用同一口径，不要重复已经给过的内容，除非数据发生了变化。

四、默认输出结构
【结论】1—2 句，回答用户真正问的问题。
【依据】2—3 条，必须带 Bar ID 或日期，以及具体指标数值。
【风险与反方】1—2 条，指出这个判断最可能错在哪里。
【观察点】1—2 条条件式：如果 A 出现则关注 B；如果 C 出现则本轮判断失效。
"""

COACH_RECENT_BARS = 40


def _coach_date(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
    except Exception:
        return '—'


def _coach_ma_periods(username):
    try:
        settings = (user_manager.get_user_config(username) or {}).get('settings') or {}
        periods = settings.get('ma_periods') or [5, 10, 20, 60]
        periods = [int(p) for p in periods if str(p).isdigit() or isinstance(p, int)]
        return periods or [5, 10, 20, 60]
    except Exception:
        return [5, 10, 20, 60]


def build_coach_context(training, include_bars=True) -> str:
    """拼陪练上下文：只取当前 Bar 及之前的可见数据，绝不包含未来 K 线"""
    kp = training['kline_processor']
    ts = training['trade_simulator']
    user = training['user']
    current = kp.get_current_bar()
    if not current:
        return '【当前状态】当前没有可用的 K 线（训练可能已结束）。'

    date = kp.get_current_date() or _coach_date(current.get('time'))
    bar_id = current.get('bar_id')
    visible = kp.get_visible_data()
    account = ts.get_account_info(date)
    rules = _review_settings(user)
    cooldown_left = kp.get_cooldown_remaining() if hasattr(kp, 'get_cooldown_remaining') else 0

    lines = [
        '【当前状态】',
        f"- 股票：{training.get('stock_code')}（训练周期：{training.get('period') or 'daily'}，数据源：{training.get('data_source') or '—'}）",
        f"- 当前 Bar：Bar {bar_id}，{date}（已收盘，这是你能看到的最新一根）",
        f"- 已完成 K 线：{len([b for b in visible if int(b.get('bar_id') or 0) >= 0])} 根",
        f"- 账户：总资产 {_num(account.get('total_assets'))}；可用现金 {_num(account.get('available_cash'))}；"
        f"总收益 {_num(account.get('total_return'))}%；浮盈 {_num(account.get('floating_pnl'))}",
    ]
    pos = account.get('position_summary')
    if pos:
        lines.append(
            f"- 持仓：{pos.get('total_shares')} 股（可卖 {pos.get('available_shares')}），"
            f"均价 {_num(pos.get('average_cost'))}，现价 {_num(pos.get('current_price'))}，"
            f"浮盈 {_num(pos.get('pnl_percent'))}%"
        )
    else:
        lines.append('- 持仓：空仓（这是新开仓问题）')
    lines.append(
        f"- 规则：止损 -{rules.get('stop_loss_percent')}%，止盈 +{rules.get('take_profit_percent')}%，"
        f"清仓后禁买 {rules.get('cooldown_bars_after_flat')} 根；"
        + (f"当前仍在禁买期，还剩 {cooldown_left} 根" if cooldown_left else "当前不在禁买期")
    )

    latest_ma_text = ''
    if include_bars and visible:
        periods = _coach_ma_periods(user)
        ma_data = kp.get_ma_data(periods)
        ma_map = {int(p): {int(item['bar_id']): item['value'] for item in series} for p, series in (ma_data or {}).items()}
        latest_ma_text = ' / '.join(
            f"MA{p} {_num(series[-1]['value'])}" for p, series in (ma_data or {}).items() if series
        )
        rows = [b for b in visible[-COACH_RECENT_BARS:] if int(b.get('bar_id') or 0) >= 0] or visible[-COACH_RECENT_BARS:]
        head = '【最近 {} 根 K 线】（Bar / 日期 / 开 / 高 / 低 / 收 / 量 / '.format(len(rows))
        head += ' / '.join(f'MA{p}' for p in periods) + '）'
        lines += ['', head, '| Bar | 日期 | 开 | 高 | 低 | 收 | 量 | ' + ' | '.join(f'MA{p}' for p in periods) + ' |',
                  '| --- | --- | --- | --- | --- | --- | --- | ' + ' | '.join('---' for _ in periods) + ' |']
        for bar in rows:
            values = []
            for p in periods:
                v = ma_map.get(p, {}).get(int(bar.get('bar_id')))
                values.append(_num(v) if v is not None else '—')
            lines.append(
                f"| {bar.get('bar_id')} | {_coach_date(bar.get('time'))} | {_num(bar.get('open'))} "
                f"| {_num(bar.get('high'))} | {_num(bar.get('low'))} | {_num(bar.get('close'))} "
                f"| {_num(bar.get('volume'), 0)} | " + ' | '.join(values) + ' |'
            )

    lines += ['', '【技术指标（当前 Bar）】']
    if latest_ma_text:
        lines.append(f'- MA：{latest_ma_text}')

    macd = (kp.get_technical_indicators('MACD') or {}).get('data') or []
    if macd:
        last = macd[-1]
        hist_tail = [_num(item.get('histogram')) for item in macd[-3:]]
        lines.append(f"- MACD：DIF {_num(last.get('dif'))} / DEA {_num(last.get('dea'))} / 柱 {_num(last.get('histogram'))}"
                     f"（最近 3 根柱：{' / '.join(hist_tail)}）")
    kdj = (kp.get_technical_indicators('KDJ') or {}).get('data') or []
    if kdj:
        last = kdj[-1]
        lines.append(f"- KDJ：K {_num(last.get('k'))} / D {_num(last.get('d'))} / J {_num(last.get('j'))}")
    rsi = (kp.get_technical_indicators('RSI') or {}).get('data') or []
    if rsi:
        last = rsi[-1]
        keys = [k for k in last.keys() if k.startswith('rsi')]
        lines.append('- RSI：' + ' / '.join(f"{k.upper()} {_num(last.get(k))}" for k in keys))
    boll = (kp.get_technical_indicators('BOLL') or {}).get('data') or []
    if boll:
        last = boll[-1]
        close = float(current.get('close') or 0)
        upper, lower, middle = last.get('upper'), last.get('lower'), last.get('middle')
        where = '—'
        try:
            if upper is not None and lower is not None and upper > lower:
                where = f"带宽位置 {round((close - lower) / (upper - lower) * 100, 1)}%"
        except Exception:
            where = '—'
        lines.append(f"- BOLL：上 {_num(upper)} / 中 {_num(middle)} / 下 {_num(lower)}（{where}）")
    if visible:
        avg_vol = sum(float(b.get('volume') or 0) for b in visible[-20:]) / min(20, len(visible))
        if avg_vol:
            lines.append(f"- 量能：当前 {_num(float(current.get('volume') or 0) / avg_vol)} 倍于近 20 根均量")

    history = ts.get_trade_history_with_bar_id() or []
    if history:
        lines += ['', f'【本轮成交（共 {len(history)} 笔，最近 5 笔）】']
        for trade in history[-5:]:
            lines.append(
                f"- Bar {trade.get('bar_id') or trade.get('bar') or '—'} {trade.get('date') or trade.get('trade_date') or '—'} "
                f"{trade.get('action') or trade.get('side') or '—'} {trade.get('quantity')} 股 @ {_num(trade.get('price'))}"
            )
    else:
        lines.append('\n【本轮成交】还没有成交（空仓起步）。')

    lines += ['', '【数据边界】以上为当前 Bar 及之前的全部可见数据；之后走势未知，不得推测。']
    return '\n'.join(lines)


@app.route('/api/training/<training_id>/coach', methods=['POST'])
def ai_coach_chat(training_id):
    """AI 实时陪练：基于当前 Bar 及之前的行情、指标与账户回答用户问题"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在或已结束'}), 404
        training = active_trainings[training_id]
        if training.get('status') == 'ended':
            return jsonify({'error': '训练已结束，陪练不可用'}), 409

        data = request.get_json(silent=True) or {}
        question = str(data.get('question') or '').strip()
        if not question:
            return jsonify({'error': '问题不能为空'}), 400
        if len(question) > 600:
            return jsonify({'error': '问题太长，请压缩到 600 字以内'}), 400

        ai_config = get_ai_config()
        if not ai_config or not ai_config.get('api_key'):
            return jsonify({'error': 'AI 接口未配置，请先在设置里填写 Base URL、模型和 API Key'}), 403

        history = data.get('history') or []
        cleaned = []
        for msg in history[-8:]:
            role = str((msg or {}).get('role') or '')
            content = str((msg or {}).get('content') or '').strip()
            if role in ('user', 'assistant') and content:
                cleaned.append({'role': role, 'content': content[:1500]})

        context = build_coach_context(training, include_bars=not cleaned)
        messages = [{'role': 'system', 'content': AI_COACH_SYSTEM_PROMPT}]
        messages.extend(cleaned)
        messages.append({'role': 'user', 'content': f"{context}\n\n【我的问题】{question}"})

        base_url = str(ai_config.get('base_url') or 'https://api.openai.com/v1').rstrip('/')
        model = ai_config.get('model') or 'deepseek-chat'
        headers = {'Authorization': f"Bearer {ai_config.get('api_key')}", 'Content-Type': 'application/json'}
        payload = {'model': model, 'messages': messages, 'temperature': 0.5, 'max_tokens': 900}

        response = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=90)
        if response.status_code != 200:
            return jsonify({'error': f'AI 接口返回 {response.status_code}: {response.text[:200]}'}), 502
        answer = (response.json().get('choices') or [{}])[0].get('message', {}).get('content') or ''
        answer = answer.strip()
        if not answer:
            return jsonify({'error': 'AI 没有返回内容，请重试'}), 502

        current = training['kline_processor'].get_current_bar() or {}
        return jsonify({
            'answer': answer,
            'meta': {
                'bar_id': current.get('bar_id'),
                'date': _coach_date(current.get('time')),
                'model': model,
                'visible_bars': len(training['kline_processor'].get_visible_data()),
                'context_chars': len(context),
            }
        })
    except Exception as e:
        print(f'AI 陪练失败: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/system/api_info', methods=['POST', 'DELETE'])
def toggle_api_info():
    """手动切开/关 API暴露"""
    try:
        if request.method == 'POST':
            data = request.get_json() or {}
            user = data.get('user', None)
            _update_api_info(user=user, enable=True)
            return jsonify({'message': 'API info exposed'})
        else:
            _update_api_info(enable=False)
            return jsonify({'message': 'API info hidden'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/system/ai-config', methods=['GET', 'POST', 'DELETE'])
def ai_config_api():
    """应用内配置 AI 接口：读当前配置 / 保存 / 清除（写入 data/.ai_tester_config.enc）"""
    try:
        if request.method == 'GET':
            cfg = get_ai_config() or {}
            key = str(cfg.get('api_key') or '')
            return jsonify({
                'configured': bool(cfg),
                'base_url': cfg.get('base_url') or '',
                'model': cfg.get('model') or '',
                'has_key': bool(key),
                'api_key_masked': (key[:6] + '...' + key[-4:]) if len(key) > 12 else ('已配置' if key else ''),
                'path': _ai_config_path(),
            })

        if request.method == 'DELETE':
            path = _ai_config_path()
            if os.path.exists(path):
                backup = path + '.bak-' + datetime.now().strftime('%Y%m%d_%H%M%S')
                os.rename(path, backup)
                return jsonify({'message': '已清除 AI 配置', 'backup': os.path.basename(backup)})
            return jsonify({'message': '当前没有 AI 配置'})

        data = request.get_json() or {}
        old = get_ai_config() or {}
        base_url = str(data.get('base_url') or old.get('base_url') or '').strip()
        model = str(data.get('model') or old.get('model') or '').strip()
        api_key = str(data.get('api_key') or '').strip() or str(old.get('api_key') or '')
        if not base_url or not model:
            return jsonify({'error': '接口地址和模型名不能为空'}), 400
        if not api_key:
            return jsonify({'error': 'API Key 不能为空'}), 400
        cfg = dict(old)
        cfg.update({'base_url': base_url, 'api_key': api_key, 'model': model})
        save_ai_config(cfg)
        masked = (api_key[:6] + '...' + api_key[-4:]) if len(api_key) > 12 else '已配置'
        return jsonify({'message': '已保存 AI 配置', 'base_url': base_url, 'model': model,
                        'api_key_masked': masked})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/system/ai-config/test', methods=['POST'])
def ai_config_test():
    """用填好的地址 / 模型 / Key 发一次极小请求；Key 留空则沿用已保存的"""
    try:
        data = request.get_json() or {}
        old = get_ai_config() or {}
        base_url = str(data.get('base_url') or old.get('base_url') or '').strip()
        model = str(data.get('model') or old.get('model') or '').strip()
        api_key = str(data.get('api_key') or '').strip() or str(old.get('api_key') or '')
        if not base_url or not model or not api_key:
            return jsonify({'ok': False, 'message': '地址 / 模型 / Key 填全后再测试'}), 400
        message = test_ai_connection(base_url, model, api_key)
        return jsonify({'ok': message.startswith('连通成功'), 'message': message})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500


@app.route('/api/training/start', methods=['POST'])
def start_training():
    """开始新的训练"""
    try:
        data = request.get_json()
        user = data.get('user') or data.get('username')
        mode = data.get('mode')
        data_source = data.get('data_source', 'akshare')
        period = data.get('period', 'daily')
        initial_capital = data.get('initial_capital', 100000)
        
        if not user:
            return jsonify({'error': '用户名不能为空'}), 400

        # 每轮开始前清掉上一轮随机选股留下的兜底提示，避免串到指定模式
        data_manager.last_random_notice = None
        
        # 创建训练会话；同一秒内连续开始两次时给 ID 加后缀，避免撞上已有会话或历史库
        base_id = f"{user}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        training_id = base_id
        suffix = 1
        while training_id in active_trainings:
            suffix += 1
            training_id = f"{base_id}_{suffix}"
        
        session_end_date = data.get('end_date')

        if mode == 'random':
            # 随机模式
            sector = data.get('sector', 'all')
            date_start = data.get('date_start', '2024-01-01')
            date_end = data.get('date_end', '2026-01-01')
            # 盲盒的「日期范围」既是抽签范围，也是本次训练的结束日期
            if not session_end_date:
                session_end_date = date_end
            try:
                stock_code, start_date = data_manager.get_random_stock(
                    sector,
                    date_start,
                    date_end,
                    source=data_source,
                    interval=period,
                )
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        else:
            # 指定模式
            stock_code = data.get('stock_code')
            start_date = data.get('start_date')
            
            if not stock_code or not start_date:
                return jsonify({'error': '股票代码和起始日期不能为空'}), 400

        if session_end_date and pd.to_datetime(session_end_date) <= pd.to_datetime(start_date):
            return jsonify({'error': f'结束日期 {session_end_date} 必须晚于起始日期 {start_date}'}), 400
        
        # 验证股票代码和日期
        validation_error = data_manager.get_training_validation_error(
            stock_code,
            start_date,
            source=data_source,
            interval=period,
        )
        if validation_error:
            return jsonify({'error': validation_error}), 400
        
        # 创建增强版K线处理器和交易模拟器
        kline_processor = KLineProcessorEnhanced(
            data_manager,
            stock_code,
            start_date,
            source=data_source,
            interval=period,
            end_date=session_end_date,
        )
        trade_simulator = TradeSimulatorEnhanced(user, initial_capital, stock_code)
        
        # 获取用户设置并应用到交易模拟器
        user_config = user_manager.get_user_config(user)
        if user_config and 'settings' in user_config:
            settings = user_config['settings']
            trade_simulator.set_commission_settings(
                settings.get('commission_rate', 0.0003),
                settings.get('min_commission', 5.0),
                settings.get('stamp_tax_rate', 0.001)
            )
        
        # 存储训练会话
        active_trainings[training_id] = {
            'user': user,
            'stock_code': stock_code,
            'start_date': start_date,
            'kline_processor': kline_processor,
            'trade_simulator': trade_simulator,
            'mode': mode,
            'data_source': data_source,
            'period': period,
            'created_at': datetime.now()
        }
        
        _update_api_info(user=user)

        # 训练一开始就落库，保证历史记录里能看到这次训练（哪怕一笔都没成交）
        try:
            user_manager.start_training_session(user, {
                'session_id': training_id,
                'stock_code': stock_code,
                'stock_name': data_manager.get_stock_name(stock_code),
                'start_date': start_date,
                'mode': mode,
                'initial_capital': trade_simulator.initial_capital,
                'commission_settings': {
                    'commission_rate': trade_simulator.commission_rate,
                    'min_commission': trade_simulator.min_commission,
                    'stamp_tax_rate': trade_simulator.stamp_tax_rate,
                },
            })
        except Exception as e:
            print(f"创建训练历史记录失败: {e}")

        
        result = {
            'id': training_id,
            'stock_code': stock_code,
            'start_date': start_date,
            'end_date': kline_processor.get_planned_end_date(),
            'mode': mode,
            'data_source': data_source,
            'period': period
        }
        notice = getattr(data_manager, 'last_random_notice', None)
        if notice:
            result['notice'] = notice
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/data', methods=['GET'])
def get_training_data(training_id):
    """获取训练数据"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        kline_processor = training['kline_processor']
        view_period = request.args.get('view_period', 'daily')
        
        # 获取当前可见的K线数据
        kline_data = kline_processor.get_visible_data(view_period=view_period)
        volume_data = kline_processor.get_volume_data(view_period=view_period)
        
        # 获取均线周期参数
        ma_periods_str = request.args.get('ma_periods', '5,10,20')
        try:
            ma_periods = [int(p) for p in ma_periods_str.split(',') if p.strip()]
        except ValueError:
            ma_periods = [5, 10, 20]
            
        ma_data = kline_processor.get_ma_data(ma_periods, view_period=view_period)
        
        # 获取股票名称
        stock_name = data_manager.get_stock_name(training['stock_code'])
        
        # 获取进度信息
        progress = kline_processor.get_progress()
        
        return jsonify({
            'stock_name': stock_name,
            'kline_data': kline_data,
            'volume_data': volume_data,
            'ma_data': ma_data,
            'progress': progress,
            'trade_markers': kline_processor.get_trade_markers() if view_period == 'daily' else [],
            'cooldown_markers': kline_processor.get_cooldown_markers() if view_period == 'daily' else [],
            'cooldown_remaining': kline_processor.get_cooldown_remaining(),
            'signal_markers': build_divergence_markers(kline_processor, training, view_period),
            'period': training.get('period', 'daily'),
            'view_period': view_period,
            'data_source': training.get('data_source', 'akshare')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/next', methods=['POST'])
def next_bar(training_id):
    """获取下一根K线"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        kline_processor = training['kline_processor']
        trade_simulator = training['trade_simulator']

        # 推进到下一根K线
        has_next = kline_processor.next_bar()
        
        if not has_next:
            # 训练结束，生成报告
            report = trade_simulator.generate_report(
                training['stock_code'],
                training['start_date'],
                kline_processor.get_current_date(),
                kline_processor.get_visible_data('daily')
            )
            
            # 保存训练记录
            session_data = {
                'session_id': training_id,
                'stock_code': training['stock_code'],
                'stock_name': data_manager.get_stock_name(training['stock_code']),
                'start_date': training['start_date'],
                'end_date': kline_processor.get_current_date(),
                'mode': training['mode'],
                'initial_capital': report['initial_capital'],
                'final_capital': report['final_capital'],
                'total_return': report['total_return'],
                'total_trades': report['total_trades'],
                'trade_win_rate': report['trade_win_rate'],
                'session_win_rate': report['session_win_rate'],
                'max_drawdown': report.get('max_drawdown', 0),
                'status': 'completed'
            }
            user_manager.save_training_session(training['user'], session_data)
            user_manager.save_report(training['user'], training_id, report)
            
            return jsonify({
                'finished': True,
                'report': report
            })
        
        # 更新交易模拟器的当前价格和bar ID
        current_bar = kline_processor.get_current_bar()
        trade_simulator.update_current_price(current_bar['close'], current_bar['bar_id'])

        current_bar['lastClose'] = kline_processor.get_previous_close()

        res = {
            'finished': False,
            'new_bar': current_bar,
            'new_volume': kline_processor.get_current_volume(),
            'progress': kline_processor.get_progress(),
            'requires_full_refresh': getattr(kline_processor, 'factor_changed', False),
            'cooldown_markers': kline_processor.get_cooldown_markers(),
            'cooldown_remaining': kline_processor.get_cooldown_remaining(),
            'signal_markers': build_divergence_markers(kline_processor, training)
        }

        color = '#000000'
        if res['new_bar']['close'] > res['new_bar']['open']:
            color = '#ff4d4f'
        elif res['new_bar']['close'] < res['new_bar']['open']:
            color = '#008000'  # 红涨绿跌

        res['new_volume']['color'] = color

        return jsonify(res)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/adjustment', methods=['POST'])
def update_adjustment(training_id):
    """更新复权设置"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        data = request.get_json()
        adjustment = data.get('adjustment', 'none')
        view_period = request.args.get('view_period', 'daily')
        
        training = active_trainings[training_id]
        kline_processor = training['kline_processor']
        
        # 更新复权设置
        kline_processor.set_adjustment(adjustment)
        
        # 获取均线周期参数
        ma_periods_str = request.args.get('ma_periods', '5,10,20')
        try:
            ma_periods = [int(p) for p in ma_periods_str.split(',') if p.strip()]
        except ValueError:
            ma_periods = [5, 10, 20]
            
        # 重新获取数据
        kline_data = kline_processor.get_visible_data(view_period=view_period)
        volume_data = kline_processor.get_volume_data(view_period=view_period)
        ma_data = kline_processor.get_ma_data(ma_periods, view_period=view_period)
        
        return jsonify({
            'kline_data': kline_data,
            'volume_data': volume_data,
            'ma_data': ma_data
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/full_data', methods=['GET'])
def get_full_data(training_id):
    """获取完整的K线数据和指标数据"""
    try:
        if training_id not in active_trainings:
            # 如果训练已结束且不在 active_trainings 中，尝试从历史记录重建所需的数据（这需要一些额外逻辑，目前先返回明确错误）
            # 或者我们可以考虑在 end_training 时不立即删除，而是标记为 ended，由客户端稍后清理
            return jsonify({'error': '训练会话已结束或不存在，无法获取完整走势'}), 404
        
        training = active_trainings[training_id]
        kline_processor = training['kline_processor']
        view_period = request.args.get('view_period', 'daily')
        
        kline_data = kline_processor.get_full_data(view_period=view_period)
        
        # 获取均线周期参数
        ma_periods_str = request.args.get('ma_periods', '5,10,20')
        try:
            ma_periods = [int(p) for p in ma_periods_str.split(',') if p.strip()]
        except ValueError:
            ma_periods = [5, 10, 20]
            
        # We also need volume data for the full range
        volume_data = []
        ma_data = {p: [] for p in ma_periods}
        
        # Save current state
        original_index = kline_processor.current_index
        
        # Set to max to calculate everything
        kline_processor.current_index = kline_processor.max_index
        
        try:
            volume_data = kline_processor.get_volume_data(view_period=view_period)
            ma_data = kline_processor.get_ma_data(ma_periods, view_period=view_period)
        finally:
            # Restore state
            kline_processor.current_index = original_index
            
        return jsonify({
            'kline_data': kline_data,
            'volume_data': volume_data,
            'ma_data': ma_data,
            'trade_markers': kline_processor.get_trade_markers() if view_period == 'daily' else [],
            'cooldown_markers': kline_processor.get_cooldown_markers() if view_period == 'daily' else [],
            'signal_markers': build_divergence_markers(kline_processor, training, view_period),
            'period': training.get('period', 'daily'),
            'view_period': view_period,
            'data_source': training.get('data_source', 'akshare')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/trade', methods=['POST'])
def execute_trade(training_id):
    """执行交易"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        data = request.get_json()
        action = data.get('action')  # 'buy' or 'sell'
        quantity = data.get('quantity')
        price_type = data.get('price_type', 'close')
        
        if not action or not quantity:
            return jsonify({'error': '交易参数不完整'}), 400
        
        training = active_trainings[training_id]
        trade_simulator = training['trade_simulator']
        kline_processor = training['kline_processor']
        
        # 获取当前价格
        current_bar = kline_processor.get_current_bar()
        current_price = current_bar['open'] if price_type == 'open' else current_bar['close']
        current_date = kline_processor.get_current_date()

        # 交易前总资产，用于历史记录里的资产变化
        try:
            assets_before = trade_simulator.get_account_info(current_date)['total_assets']
        except Exception:
            assets_before = None
        
        # 执行交易
        if action == 'buy':
            result = trade_simulator.buy(quantity, current_price, current_date)
        elif action == 'sell':
            result = trade_simulator.sell(quantity, current_price, current_date)
        else:
            return jsonify({'error': '无效的交易操作'}), 400
        
        if result['success']:
            # 添加交易标记到K线图
            kline_processor.add_trade_marker(action, current_price)

            # 落库这笔交易，供历史记录回看
            try:
                assets_after = trade_simulator.get_account_info(current_date)['total_assets']
                trade_record = dict(result['trade'])
                trade_record['total_assets_before'] = assets_before if assets_before is not None else assets_after
                trade_record['total_assets_after'] = assets_after
                user_manager.record_trade(training['user'], training_id, trade_record)
            except Exception as e:
                print(f"记录交易到历史库失败: {e}")

            # 清仓（持仓归零）后开启禁买冷却期
            if action == 'sell' and getattr(trade_simulator, 'total_shares', 0) <= 0:
                cooldown_bars = get_cooldown_bars_setting(training.get('user'))
                if cooldown_bars > 0:
                    kline_processor.start_cooldown(cooldown_bars)

            return jsonify({
                'success': True,
                'trade': result['trade'],
                'trade_markers': kline_processor.get_trade_markers(),
                'cooldown_markers': kline_processor.get_cooldown_markers(),
                'cooldown_remaining': kline_processor.get_cooldown_remaining(),
                'signal_markers': build_divergence_markers(kline_processor, training)
            })
        else:
            return jsonify({'error': result['message']}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/account', methods=['GET'])
def get_account_info(training_id):
    """获取账户信息"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        trade_simulator = training['trade_simulator']

        current_date = training['kline_processor'].get_current_date()

        account_info = trade_simulator.get_account_info(current_date)
        return jsonify(account_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/trade_records', methods=['GET'])
def get_trade_records(training_id):
    """获取最新交易记录明细"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        trade_simulator = training['trade_simulator']
        
        records = trade_simulator.get_trade_history_with_bar_id()
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/indicators/<indicator_type>', methods=['GET'])
def get_technical_indicators(training_id, indicator_type):
    """获取技术指标数据"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        kline_processor = training['kline_processor']
        view_period = request.args.get('view_period', 'daily')
        
        # 获取用户自定义的技术指标参数
        user = training['user']
        user_config = user_manager.get_user_config(user)
        kwargs = {}
        if user_config and 'settings' in user_config and 'indicators' in user_config['settings']:
            ind_settings = user_config['settings']['indicators']
            ind_type_lower = indicator_type.lower()
            if ind_type_lower in ind_settings:
                kwargs = ind_settings[ind_type_lower]
                
        indicators = kline_processor.get_technical_indicators(indicator_type.upper(), view_period=view_period, **kwargs)
        return jsonify(indicators)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/sync_status', methods=['GET'])
def get_sync_status(training_id):
    """获取精简同步状态"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        kline_processor = training['kline_processor']
        
        return jsonify({
            'current_bar_id': kline_processor.get_current_bar_id(),
            'trade_markers_count': len(kline_processor.get_trade_markers())
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/end', methods=['POST'])
def end_training(training_id):
    """结束训练"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        trade_simulator = training['trade_simulator']
        kline_processor = training['kline_processor']
        
        # Inject session_id into trade_simulator before generating report
        trade_simulator.session_id = training_id
        
        # 生成报告
        report = trade_simulator.generate_report(
            training['stock_code'],
            training['start_date'],
            kline_processor.get_current_date(),
            kline_processor.get_visible_data('daily')
        )
        
        # 保存训练记录
        session_data = {
            'session_id': training_id,
            'stock_code': training['stock_code'],
            'stock_name': data_manager.get_stock_name(training['stock_code']),
            'start_date': training['start_date'],
            'end_date': kline_processor.get_current_date(),
            'mode': training['mode'],
            'initial_capital': report['initial_capital'],
            'final_capital': report['final_capital'],
            'total_return': report['total_return'],
            'total_trades': report['total_trades'],
            'trade_win_rate': report['trade_win_rate'],
            'session_win_rate': report['session_win_rate'],
            'max_drawdown': report.get('max_drawdown', 0),
            'status': 'ended'
        }
        user_manager.save_training_session(training['user'], session_data)
        user_manager.save_report(training['user'], training_id, report)
        
        # 清理训练会话
        # del active_trainings[training_id] # 不要立即删除，因为客户端可能还需要请求 full_data
        active_trainings[training_id]['status'] = 'ended'
        
        _update_api_info(user=training['user'])
        
        return jsonify(report)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/cleanup', methods=['POST'])
def cleanup_training(training_id):
    """清理已结束的训练会话"""
    try:
        if training_id in active_trainings:
            del active_trainings[training_id]
        return jsonify({'message': '清理成功'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/reset', methods=['POST'])
def reset_training(training_id):
    """重置训练"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        
        # 重置K线处理器
        training['kline_processor'].reset()
        
        # 重置交易模拟器
        training['trade_simulator'].reset()
        
        return jsonify({'message': '训练已重置'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/history', methods=['GET'])
def get_training_history(training_id):
    """获取训练历史记录"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
        
        training = active_trainings[training_id]
        trade_simulator = training['trade_simulator']
        kline_processor = training['kline_processor']
        
        # 获取交易历史（包含bar ID）
        trade_history = trade_simulator.get_trade_history_with_bar_id()
        
        # 获取每个bar的账户状态历史
        progress = kline_processor.get_progress()
        
        return jsonify({
            'trade_history': trade_history,
            'progress': progress,
            'trade_markers': kline_processor.get_trade_markers()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/<training_id>/chip_distribution', methods=['GET'])
def get_chip_distribution(training_id):
    """获取筹码分布（换手率衰减模型）"""
    try:
        if training_id not in active_trainings:
            return jsonify({'error': '训练会话不存在'}), 404
            
        kline_processor = active_trainings[training_id]['kline_processor']
        view_period = request.args.get('view_period', 'daily')
        
        # 可选增加 bins 参数，如果前端要求更精细的分布
        bins = int(request.args.get('bins', 80))
        chip_dist = kline_processor.get_volume_profile(bins=bins, view_period=view_period)
        
        return jsonify(chip_dist)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data/sources', methods=['GET'])
def get_data_sources():
    """返回可选数据源与可用性。"""
    try:
        return jsonify({'sources': data_manager.get_available_sources()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data/stock_universe', methods=['GET'])
def get_stock_universe():
    """按市场返回股票代码列表，供批量补数使用。"""
    try:
        market = request.args.get('market', 'all')
        stock_codes = data_manager.get_stock_universe(market=market)
        return jsonify({
            'market': market,
            'count': len(stock_codes),
            'stock_codes': stock_codes,
            'stock_list_ready': data_manager.stock_list is not None,
            'stock_list_pending': data_manager.is_stock_list_pending(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/data/sync', methods=['POST'])
def sync_offline_data():
    """使用在线数据源增量补充离线数据。"""
    try:
        data = request.get_json() or {}
        stock_code = (data.get('stock_code') or '').strip()
        source = data.get('source', 'akshare')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        force_full = bool(data.get('force_full', False))

        if not stock_code:
            return jsonify({'error': '股票代码不能为空'}), 400
        if source == 'offline':
            return jsonify({'error': '请先选择在线数据源'}), 400

        result = data_manager.sync_offline_data(
            stock_code=stock_code,
            source=source,
            start_date=start_date,
            end_date=end_date,
            force_full=force_full,
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/training/analyze_report', methods=['POST'])
def analyze_report():
    """使用AI分析复盘报告"""
    try:
        data = request.get_json()
        report = data.get('report')
        user = data.get('user')
        
        if not report or not user:
            return jsonify({'error': '缺少必要的参数'}), 400
            
        user_config = user_manager.get_user_config(user)
        if not user_config or not user_config.get('settings', {}).get('enable_ai_api', False):
            return jsonify({'error': '未开启AI分析功能'}), 403

        # 已经存在点评就直接复用，避免重复消耗 token；要重跑必须显式 force
        session_id = report.get('session_id')
        force = bool(data.get('force'))
        if session_id and not force:
            try:
                record = user_manager.get_report_and_analysis(user, session_id)
                if record.get('ai_analysis'):
                    return jsonify({'ai_commentary': record['ai_analysis'], 'cached': True})
            except Exception as e:
                print(f"读取已存 AI 点评失败（继续重新生成）: {e}")

        ai_commentary, review_result = analyze_report_with_ai(report, user)
        # 保存到历史库，之后在主菜单里可以随时回看（结构化点评绑同一 session_id）
        try:
            if session_id:
                user_manager.save_ai_analysis(
                    user, session_id, ai_commentary,
                    fill_reviews=None,  # V2.3：不再生成逐笔短评；COALESCE 会保留旧报告的旧值
                    key_trade_reviews=(review_result or {}).get('key_trade_reviews'),
                    review_meta=review_result,
                )
        except Exception as e:
            print(f"保存 AI 点评失败: {e}")
        return jsonify({'ai_commentary': ai_commentary, 'cached': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/history', methods=['GET'])
def list_user_training_history(username):
    """列出该用户的全部历史训练记录"""
    try:
        limit = request.args.get('limit', default=100, type=int)
        history = user_manager.get_training_history(username, limit=limit)
        return jsonify({'history': history, 'total': len(history)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/history/<session_id>', methods=['GET'])
def get_training_history_detail(username, session_id):
    """读取某次训练的保存报告与 AI 点评"""
    try:
        record = user_manager.get_report_and_analysis(username, session_id)
        summary = None
        for item in user_manager.get_training_history(username, limit=500):
            if item.get('session_id') == session_id:
                summary = item
                break
        return jsonify({
            'session': summary,
            'report': record.get('report'),
            'ai_analysis': record.get('ai_analysis'),
            'ai_updated_at': record.get('ai_updated_at')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/history/<session_id>/export', methods=['GET'])
def export_training_report_markdown(username, session_id):
    """导出单期复盘的 Markdown 数据包（走势 + 全部数据 + AI 原文）"""
    try:
        record = user_manager.get_report_and_analysis(username, session_id)
        report = record.get('report')
        if not report:
            return jsonify({'error': '这次训练没有保存报告，无法导出'}), 404
        session = None
        for item in user_manager.get_training_history(username, limit=500):
            if item.get('session_id') == session_id:
                session = item
                break
        try:
            archive = review_history.load(user_manager.users_dir, username)
            issues = archive.get('issues') or []
        except Exception:
            issues = []
        markdown = build_report_export_markdown(
            username, session_id, session, report,
            record.get('ai_analysis'), record.get('review_meta'), issues
        )
        filename = f"{report.get('stock_code') or 'report'}_{session_id}_复盘数据包.md"
        return jsonify({'markdown': markdown, 'filename': filename, 'chars': len(markdown)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/history/<session_id>', methods=['DELETE'])
def delete_training_history(username, session_id):
    """删除某条历史训练记录（含对应的复盘报告与 AI 点评）"""
    try:
        ok = user_manager.delete_training_session(username, session_id)
        if not ok:
            return jsonify({'error': '删除失败，记录可能已不存在'}), 404
        return jsonify({'success': True, 'session_id': session_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/history/<session_id>/ai', methods=['POST'])
def analyze_history_session(username, session_id):
    """对已保存的历史训练重新做 AI 点评（已有点评则直接复用）"""
    try:
        user_config = user_manager.get_user_config(username)
        if not user_config or not user_config.get('settings', {}).get('enable_ai_api', False):
            return jsonify({'error': '未开启AI分析功能'}), 403

        record = user_manager.get_report_and_analysis(username, session_id)
        if record.get('ai_analysis'):
            return jsonify({'ai_commentary': record['ai_analysis'], 'cached': True})

        report = record.get('report')
        if not report:
            return jsonify({'error': '这次训练没有保存报告，无法做 AI 复盘'}), 404

        if not report.get('session_id'):
            report['session_id'] = session_id

        ai_commentary, review_result = analyze_report_with_ai(report, user)
        try:
            user_manager.save_ai_analysis(
                username, session_id, ai_commentary,
                fill_reviews=None,  # V2.3：不再生成逐笔短评；COALESCE 会保留旧报告的旧值
                key_trade_reviews=(review_result or {}).get('key_trade_reviews'),
                review_meta=review_result,
            )
        except Exception as e:
            print(f"保存 AI 点评失败: {e}")
        return jsonify({'ai_commentary': ai_commentary, 'cached': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<username>/history/<session_id>/fill-reviews', methods=['GET'])
def get_fill_reviews(username, session_id):
    """读取某次复盘的结构化点评（曲线交互用）

    V2.3：新报告只写 key_trade_reviews。接口地址沿用旧名（不改路由，避免破坏旧前端），
    fill_reviews 字段标记为 legacy——旧报告里 V2.2 生成的逐笔短评仍原样返回，新版界面不再展示。
    """
    try:
        record = user_manager.get_report_and_analysis(username, session_id)
        reviews = record.get('fill_reviews') or []
        keys = record.get('key_trade_reviews') or []
        meta = record.get('review_meta') or {}
        rule_check = meta.get('rule_check') or []
        report = record.get('report') or {}
        fills = []
        coverage = {'trades': 0, 'used_trades': 0, 'skipped_trades': 0, 'cycles': 0, 'key_trades': len(keys), 'rules': len(rule_check)}
        if report:
            mapping = build_fill_mapping(report, max_fills=AI_REVIEW_MAX_FILLS)
            fills = [{
                'fill_id': f['fill_id'],
                'bar_id': f['bar_id'],
                'date': f['date'],
                'side': f['side'],
                'quantity': f['quantity'],
                'price': f['price'],
                'action_type': f['action_type'],
                'trade_cycle_id': f['trade_cycle_id'],
                'position_before': f['position_before'],
                'position_after': f['position_after'],
                'mapping_status': f['mapping_status'],
            } for f in mapping['fills']]
            coverage = {
                'trades': mapping.get('total_trades', len(fills)),
                'used_trades': mapping.get('used_trades', len(fills)),
                'skipped_trades': mapping.get('skipped_trades', 0),
                'cycles': len({f['trade_cycle_id'] for f in fills if f.get('trade_cycle_id')}),
                'key_trades': len(keys),
                'rules': len(rule_check),
            }
        return jsonify({
            'session_id': session_id,
            'available': bool(keys or reviews or rule_check),
            'has_ai_analysis': bool(record.get('ai_analysis')),
            'fill_reviews': reviews,           # legacy：V2.2 逐笔短评，V2.3 界面不再展示
            'legacy_fill_reviews': True,
            'key_trade_reviews': keys,
            'rule_check': rule_check,
            'rules_configured': len(_user_trading_rules(username)),
            'fills': fills,
            'coverage': coverage,
            'errors': meta.get('errors') or [],
            'review_id': meta.get('review_id') or '',
            'model': meta.get('model') or record.get('ai_model') or '',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'active_trainings': len(active_trainings)
    })

if __name__ == '__main__':
    # 确保数据目录存在
    os.makedirs('../data', exist_ok=True)
    os.makedirs('../users', exist_ok=True)
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=5000, debug=True)
