"""历史问题档案（trade_review_history.json）

V2.1 的机器协议落地：AI 只能追加证据与观察结果，用户维护的字段优先保留，
任何修改都留版本记录，不允许删除问题。
"""
import os
import json
import shutil
from datetime import datetime

SCHEMA_VERSION = '1.0'
FILE_NAME = 'trade_review_history.json'
BACKUP_DIR = 'review_history_backups'

AI_STATUSES = ('NEW', 'RECURRED', 'IMPROVING', 'NOT_OBSERVED', 'INSUFFICIENT_DATA')
USER_STATUSES = ('待改进', '持续观察', '已改善', '已解决', '暂不处理')
CATEGORIES = (
    '追涨买入', '过早买入', '亏损加仓', '高位连续加仓', '延迟止损', '过早止盈',
    '盈利回吐', '反复交易', '仓位过重', '持仓管理不合理', '策略执行不一致', '其他',
)
SEVERITIES = ('HIGH', 'MEDIUM', 'LOW')
CONFIDENCES = ('HIGH', 'MEDIUM', 'LOW')
OPERATIONS = ('CREATE', 'UPDATE', 'NO_CHANGE')

# 用户维护字段：AI 合并时永不覆盖
USER_FIELDS = ('title', 'description', 'category', 'recommended_rule', 'user_note', 'status_user')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today():
    return datetime.now().strftime('%Y-%m-%d')


def _user_dir(users_dir, username):
    return os.path.join(users_dir, username)


def store_path(users_dir, username):
    return os.path.join(_user_dir(users_dir, username), FILE_NAME)


def empty_archive(username):
    return {
        'schema_version': SCHEMA_VERSION,
        'user': username,
        'created_at': _now(),
        'updated_at': _now(),
        'review_count': 0,
        'issues': [],
        'audit': [],
    }


def load(users_dir, username):
    path = store_path(users_dir, username)
    if not os.path.exists(path):
        return empty_archive(username)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return empty_archive(username)
        data.setdefault('schema_version', SCHEMA_VERSION)
        data.setdefault('issues', [])
        data.setdefault('audit', [])
        data.setdefault('review_count', 0)
        data.setdefault('user', username)
        return data
    except Exception as e:
        print(f'读取历史问题档案失败: {e}')
        return empty_archive(username)


def _atomic_save(users_dir, username, data):
    path = store_path(users_dir, username)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data['updated_at'] = _now()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save(users_dir, username, data):
    _atomic_save(users_dir, username, data)


def _next_issue_id(issues):
    used = set()
    for i in issues:
        iid = str(i.get('issue_id') or '')
        if iid.startswith('ISS-') and iid[4:].isdigit():
            used.add(int(iid[4:]))
    n = 1
    while n in used:
        n += 1
    return f'ISS-{n:04d}'


# ---------------------------------------------------------------- 校验

def validate_ai_payload(payload):
    """校验 AI 输出的历史问题 JSON，返回 (ok, errors)"""
    errors = []
    if not isinstance(payload, dict):
        return False, ['payload 不是 JSON 对象']
    if payload.get('schema_version') != SCHEMA_VERSION:
        errors.append(f'schema_version 必须为 {SCHEMA_VERSION}')
    updates = payload.get('history_updates')
    if not isinstance(updates, list):
        errors.append('history_updates 必须是数组')
        return False, errors
    for idx, item in enumerate(updates):
        if not isinstance(item, dict):
            errors.append(f'history_updates[{idx}] 不是对象')
            continue
        op = item.get('operation')
        if op not in OPERATIONS:
            errors.append(f'history_updates[{idx}].operation 非法: {op}')
        status = item.get('observation_status')
        if status is not None and status not in AI_STATUSES:
            errors.append(f'history_updates[{idx}].observation_status 非法: {status}')
        if op == 'CREATE':
            if item.get('category') not in CATEGORIES:
                errors.append(f'history_updates[{idx}].category 非法: {item.get("category")}')
            if not str(item.get('title') or '').strip():
                errors.append(f'history_updates[{idx}] CREATE 缺少 title')
        if op == 'UPDATE' and not item.get('target_issue_id'):
            errors.append(f'history_updates[{idx}] UPDATE 缺少 target_issue_id')
        evidence = item.get('evidence')
        if evidence is not None and not isinstance(evidence, list):
            errors.append(f'history_updates[{idx}].evidence 必须是数组')
    return len(errors) == 0, errors


# ---------------------------------------------------------------- 合并

def _append_evidence(issue, evidence, review_id, source='ai'):
    existing = issue.setdefault('evidence', [])
    added = 0
    for ev in evidence or []:
        if not isinstance(ev, dict):
            continue
        item = {
            'review_id': review_id,
            'symbol': str(ev.get('symbol') or ''),
            'date': str(ev.get('date') or ''),
            'bar_id': ev.get('bar_id'),
            'fill_id': str(ev.get('fill_id') or ''),
            'description': str(ev.get('description') or ''),
            'source': source,
            'added_at': _now(),
        }
        key = (item['date'], item['bar_id'], item['fill_id'], item['description'])
        if any((e.get('date'), e.get('bar_id'), e.get('fill_id'), e.get('description')) == key for e in existing):
            continue
        existing.append(item)
        added += 1
    return added


def _append_observation(issue, review_id, status, observation, rationale):
    issue.setdefault('ai_observations', []).append({
        'review_id': review_id,
        'at': _now(),
        'observation_status': status or 'INSUFFICIENT_DATA',
        'observation': str(observation or ''),
        'rationale': str(rationale or ''),
    })


def apply_ai_updates(users_dir, username, payload, review_id):
    """把一次复盘产出的 history_updates 合并进档案

    返回 {'created': n, 'updated': n, 'ignored': n, 'errors': [...]}
    """
    ok, errors = validate_ai_payload(payload)
    result = {'created': 0, 'updated': 0, 'ignored': 0, 'errors': errors, 'valid': ok}
    if not ok:
        # Schema 不合格时不动原档案，避免污染
        return result

    archive = load(users_dir, username)
    issues = archive.setdefault('issues', [])
    if not isinstance(issues, list):
        issues = archive['issues'] = []
    by_id = {i.get('issue_id'): i for i in issues if i.get('issue_id')}

    for item in payload.get('history_updates') or []:
        op = item.get('operation')
        if op == 'CREATE':
            status = item.get('observation_status') or 'NEW'
            new_issue = {
                'issue_id': _next_issue_id(issues),
                'category': item.get('category'),
                'title': str(item.get('title') or '').strip(),
                'description': str(item.get('observation') or item.get('description') or '').strip(),
                'severity': item.get('severity') if item.get('severity') in SEVERITIES else 'MEDIUM',
                'confidence': item.get('confidence') if item.get('confidence') in CONFIDENCES else 'MEDIUM',
                'status_ai': status,
                'status_user': '待改进',
                'first_seen': _today(),
                'last_seen': _today(),
                'last_review_id': review_id,
                'occurrence_count': 1,
                'evidence': [],
                'ai_observations': [],
                'recommended_rule': str(item.get('recommended_rule') or ''),
                'validation_metric': str(item.get('validation_metric') or ''),
                'user_note': '',
                'user_edited_fields': {},
                'versions': [{
                    'at': _now(), 'review_id': review_id, 'by': 'ai', 'op': 'CREATE',
                    'detail': f'新问题：{item.get("title")}',
                }],
            }
            _append_evidence(new_issue, item.get('evidence'), review_id)
            _append_observation(new_issue, review_id, status, item.get('observation'), item.get('rationale'))
            issues.append(new_issue)
            by_id[new_issue['issue_id']] = new_issue
            result['created'] += 1
            archive.setdefault('audit', []).append({
                'at': _now(), 'review_id': review_id, 'by': 'ai', 'op': 'CREATE',
                'issue_id': new_issue['issue_id'], 'detail': new_issue['title'],
            })
            continue

        target_id = item.get('target_issue_id')
        target = by_id.get(target_id)
        if not target:
            result['ignored'] += 1
            result['errors'].append(f'找不到 target_issue_id={target_id}，已跳过（不新建）')
            continue

        status = item.get('observation_status') or 'INSUFFICIENT_DATA'
        _append_observation(target, review_id, status, item.get('observation'), item.get('rationale'))
        _append_evidence(target, item.get('evidence'), review_id)
        target['last_review_id'] = review_id
        if op == 'UPDATE':
            target['status_ai'] = status
            target['last_seen'] = _today()
            if status == 'RECURRED':
                target['occurrence_count'] = int(target.get('occurrence_count') or 0) + 1
            # 用户编辑过这些字段就不覆盖
            edited = target.get('user_edited_fields') or {}
            for key, src in (('recommended_rule', 'recommended_rule'), ('validation_metric', 'validation_metric')):
                if key not in edited and item.get(src):
                    target[key] = str(item.get(src))
            target.setdefault('versions', []).append({
                'at': _now(), 'review_id': review_id, 'by': 'ai', 'op': 'UPDATE',
                'detail': f'观察结果：{status}',
            })
            result['updated'] += 1
            archive.setdefault('audit', []).append({
                'at': _now(), 'review_id': review_id, 'by': 'ai', 'op': 'UPDATE',
                'issue_id': target_id, 'detail': status,
            })
        else:
            result['ignored'] += 1
            target.setdefault('versions', []).append({
                'at': _now(), 'review_id': review_id, 'by': 'ai', 'op': 'NO_CHANGE',
                'detail': status,
            })

    archive['review_count'] = int(archive.get('review_count') or 0) + 1
    _atomic_save(users_dir, username, archive)
    return result


# ---------------------------------------------------------------- 用户编辑

def update_user_fields(users_dir, username, issue_id, fields):
    """只允许改用户维护字段；记录编辑痕迹，AI 之后不再覆盖"""
    archive = load(users_dir, username)
    issue = next((i for i in archive.get('issues') or [] if i.get('issue_id') == issue_id), None)
    if not issue:
        return False, '问题不存在'
    allowed = set(USER_FIELDS)
    changed = {}
    for key, value in (fields or {}).items():
        if key not in allowed:
            continue
        if key == 'status_user' and value not in USER_STATUSES:
            return False, f'status_user 非法: {value}'
        if key == 'category' and value not in CATEGORIES:
            return False, f'category 非法: {value}'
        issue[key] = value
        changed[key] = value
        issue.setdefault('user_edited_fields', {})[key] = _now()
    if not changed:
        return False, '没有可保存的字段'
    issue.setdefault('versions', []).append({
        'at': _now(), 'review_id': '', 'by': 'user', 'op': 'EDIT',
        'detail': '修改字段：' + '、'.join(changed.keys()),
    })
    archive.setdefault('audit', []).append({
        'at': _now(), 'review_id': '', 'by': 'user', 'op': 'EDIT',
        'issue_id': issue_id, 'detail': '、'.join(changed.keys()),
    })
    _atomic_save(users_dir, username, archive)
    return True, changed


# ---------------------------------------------------------------- 查询 / 导出

def summary(archive):
    issues = archive.get('issues') or []
    counts = {
        'total': len(issues),
        'recurring': sum(1 for i in issues if i.get('status_ai') == 'RECURRED'),
        'improving': sum(1 for i in issues if i.get('status_ai') == 'IMPROVING'),
        'new': sum(1 for i in issues if i.get('status_ai') == 'NEW'),
        'not_observed': sum(1 for i in issues if i.get('status_ai') == 'NOT_OBSERVED'),
        'insufficient': sum(1 for i in issues if i.get('status_ai') == 'INSUFFICIENT_DATA'),
        'pending': sum(1 for i in issues if i.get('status_user') == '待改进'),
        'observing': sum(1 for i in issues if i.get('status_user') == '持续观察'),
        'resolved': sum(1 for i in issues if i.get('status_user') == '已解决'),
    }
    return counts


def query(archive, category='', ai_status='', user_status='', severity='', keyword=''):
    items = archive.get('issues') or []
    out = []
    kw = (keyword or '').strip().lower()
    for i in items:
        if category and i.get('category') != category:
            continue
        if ai_status and i.get('status_ai') != ai_status:
            continue
        if user_status and i.get('status_user') != user_status:
            continue
        if severity and i.get('severity') != severity:
            continue
        if kw:
            haystack = ' '.join(str(i.get(k) or '') for k in ('title', 'description', 'user_note', 'recommended_rule'))
            if kw not in haystack.lower():
                continue
        out.append(i)
    return out


def issues_for_prompt(archive, limit=20):
    """只把未解决/待改进/持续观察的问题传给 AI，控制提示词体积"""
    active_status = ('待改进', '持续观察', '已改善')
    items = [i for i in (archive.get('issues') or []) if i.get('status_user') in active_status]
    items = sorted(items, key=lambda i: str(i.get('last_seen') or ''), reverse=True)[:limit]
    payload = []
    for i in items:
        payload.append({
            'issue_id': i.get('issue_id'),
            'category': i.get('category'),
            'title': i.get('title'),
            'severity': i.get('severity'),
            'description': i.get('description'),
            'status_ai': i.get('status_ai'),
            'status_user': i.get('status_user'),
            'occurrence_count': i.get('occurrence_count'),
            'first_seen': i.get('first_seen'),
            'last_seen': i.get('last_seen'),
            'recommended_rule': i.get('recommended_rule'),
            'validation_metric': i.get('validation_metric'),
            'user_note': i.get('user_note'),
            'recent_evidence': (i.get('evidence') or [])[-3:],
        })
    return {'schema_version': SCHEMA_VERSION, 'issues': payload}


def export_markdown(archive):
    s = summary(archive)
    lines = [
        f"# 交易历史问题档案（{archive.get('user')}）",
        '',
        f"- 更新时间：{archive.get('updated_at')}",
        f"- 共复盘次数：{archive.get('review_count')}",
        f"- 问题总数：{s['total']}（持续出现 {s['recurring']} / 有改善迹象 {s['improving']} / 新发现 {s['new']}）",
        f"- 用户状态：待改进 {s['pending']} / 持续观察 {s['observing']} / 已解决 {s['resolved']}",
        '',
    ]
    for i in archive.get('issues') or []:
        lines.append(f"## {i.get('issue_id')} {i.get('title')}")
        lines.append(f"- 分类：{i.get('category')}｜严重程度：{i.get('severity')}｜置信度：{i.get('confidence')}")
        lines.append(f"- AI 观察：{i.get('status_ai')}｜用户状态：{i.get('status_user')}｜出现次数：{i.get('occurrence_count')}")
        lines.append(f"- 首次发现：{i.get('first_seen')}｜最近发现：{i.get('last_seen')}｜最近复盘：{i.get('last_review_id')}")
        if i.get('description'):
            lines.append(f"- 描述：{i.get('description')}")
        if i.get('recommended_rule'):
            lines.append(f"- 建议规则：{i.get('recommended_rule')}")
        if i.get('validation_metric'):
            lines.append(f"- 验证指标：{i.get('validation_metric')}")
        if i.get('user_note'):
            lines.append(f"- 个人备注：{i.get('user_note')}")
        ev = i.get('evidence') or []
        if ev:
            lines.append('')
            lines.append('| 日期 | Bar | fill_id | 证据 | 复盘 |')
            lines.append('| --- | --- | --- | --- | --- |')
            for e in ev:
                lines.append(f"| {e.get('date')} | {e.get('bar_id')} | {e.get('fill_id')} | {e.get('description')} | {e.get('review_id')} |")
        lines.append('')
    return '\n'.join(lines)


# ---------------------------------------------------------------- 备份 / 恢复

def backup(users_dir, username):
    src = store_path(users_dir, username)
    if not os.path.exists(src):
        return None
    bdir = os.path.join(_user_dir(users_dir, username), BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    name = f"trade_review_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    dst = os.path.join(bdir, name)
    shutil.copy2(src, dst)
    return name


def list_backups(users_dir, username):
    bdir = os.path.join(_user_dir(users_dir, username), BACKUP_DIR)
    if not os.path.isdir(bdir):
        return []
    names = sorted((n for n in os.listdir(bdir) if n.endswith('.json')), reverse=True)
    return [{'name': n, 'size': os.path.getsize(os.path.join(bdir, n))} for n in names]


def restore(users_dir, username, name):
    if not name or '/' in name or '\\' in name or '..' in name:
        return False, '备份文件名非法'
    bdir = os.path.join(_user_dir(users_dir, username), BACKUP_DIR)
    src = os.path.join(bdir, name)
    if not os.path.exists(src):
        return False, '备份不存在'
    try:
        with open(src, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, f'备份文件不是合法 JSON: {e}'
    if not isinstance(data, dict) or 'issues' not in data:
        return False, '备份内容缺少 issues'
    # 恢复前把当前档案再备份一次，避免恢复不可逆
    backup(users_dir, username)
    _atomic_save(users_dir, username, data)
    return True, '已从备份恢复'
