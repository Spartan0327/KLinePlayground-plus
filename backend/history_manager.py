import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd

class HistoryManager:
    """历史记录管理器，负责存储和管理用户的训练历史记录"""
    
    def __init__(self, users_dir='../users'):
        self.users_dir = users_dir
    
    def _get_user_db_path(self, username: str) -> str:
        """获取用户数据库路径"""
        user_dir = os.path.join(self.users_dir, username)
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, 'training_history.db')
    
    def _init_user_history_db(self, username: str):
        """初始化用户历史记录数据库"""
        db_path = self._get_user_db_path(username)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 创建训练会话表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT,
                mode TEXT NOT NULL,
                initial_capital REAL NOT NULL,
                final_capital REAL,
                total_return REAL,
                max_drawdown REAL,
                total_trades INTEGER DEFAULT 0,
                trade_win_rate REAL DEFAULT 0,
                session_win_rate REAL DEFAULT 0,
                total_bars INTEGER DEFAULT 0,
                completed_bars INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                commission_settings TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        ''')
        
        # 创建K线历史表（记录每个bar的状态）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bar_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                bar_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                open_price REAL NOT NULL,
                high_price REAL NOT NULL,
                low_price REAL NOT NULL,
                close_price REAL NOT NULL,
                volume REAL NOT NULL,
                total_assets REAL NOT NULL,
                available_cash REAL NOT NULL,
                position_value REAL NOT NULL,
                floating_pnl REAL NOT NULL,
                total_shares INTEGER DEFAULT 0,
                average_cost REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES training_sessions (session_id)
            )
        ''')
        
        # 创建交易历史表（记录每笔交易）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                bar_id INTEGER NOT NULL,
                trade_date TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                commission REAL NOT NULL,
                stamp_tax REAL NOT NULL,
                net_amount REAL NOT NULL,
                total_assets_before REAL NOT NULL,
                total_assets_after REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES training_sessions (session_id)
            )
        ''')
        
        # 创建用户统计表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                total_sessions INTEGER DEFAULT 0,
                completed_sessions INTEGER DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                total_return_sum REAL DEFAULT 0,
                best_return REAL DEFAULT 0,
                worst_return REAL DEFAULT 0,
                avg_trade_win_rate REAL DEFAULT 0,
                avg_session_win_rate REAL DEFAULT 0,
                total_commission_paid REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建会话报告表（保存复盘报告 JSON 与 AI 点评文本）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_reports (
                session_id TEXT PRIMARY KEY,
                report_json TEXT,
                ai_analysis TEXT,
                ai_model TEXT,
                ai_updated_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self._ensure_report_columns(cursor)

        conn.commit()
        conn.close()

    def _ensure_report_columns(self, cursor):
        """为老库补上 V2.2 的结构化点评列（幂等）"""
        cursor.execute("PRAGMA table_info(session_reports)")
        existing = {row[1] for row in cursor.fetchall()}
        for name in ('fill_reviews_json', 'key_trade_reviews_json', 'review_meta_json'):
            if name not in existing:
                cursor.execute(f"ALTER TABLE session_reports ADD COLUMN {name} TEXT")

    def start_training_session(self, username: str, session_data: Dict) -> bool:
        """开始新的训练会话"""
        conn = None
        try:
            self._init_user_history_db(username)
            db_path = self._get_user_db_path(username)
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 插入训练会话记录
            cursor.execute('''
                INSERT INTO training_sessions 
                (session_id, stock_code, stock_name, start_date, mode, initial_capital, commission_settings)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_data['session_id'],
                session_data['stock_code'],
                session_data.get('stock_name', ''),
                session_data['start_date'],
                session_data['mode'],
                session_data['initial_capital'],
                json.dumps(session_data.get('commission_settings', {}))
            ))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"开始训练会话失败: {e}")
            if conn is not None:
                conn.close()
            return False
    
    def record_bar_state(self, username: str, session_id: str, bar_data: Dict) -> bool:
        """记录每个bar的状态"""
        conn = None
        try:
            db_path = self._get_user_db_path(username)
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO bar_history 
                (session_id, bar_id, date, open_price, high_price, low_price, close_price, volume,
                 total_assets, available_cash, position_value, floating_pnl, total_shares, average_cost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                bar_data['bar_id'],
                bar_data['date'],
                bar_data['open_price'],
                bar_data['high_price'],
                bar_data['low_price'],
                bar_data['close_price'],
                bar_data['volume'],
                bar_data['total_assets'],
                bar_data['available_cash'],
                bar_data['position_value'],
                bar_data['floating_pnl'],
                bar_data.get('total_shares', 0),
                bar_data.get('average_cost', 0)
            ))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"记录bar状态失败: {e}")
            if conn is not None:
                conn.close()
            return False
    
    def record_trade(self, username: str, session_id: str, trade_data: Dict) -> bool:
        """记录交易"""
        conn = None
        try:
            db_path = self._get_user_db_path(username)
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trade_history 
                (session_id, bar_id, trade_date, action, quantity, price, amount, commission, stamp_tax, 
                 net_amount, total_assets_before, total_assets_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id,
                trade_data['bar_id'],
                trade_data['trade_date'],
                trade_data['action'],
                trade_data['quantity'],
                trade_data['price'],
                trade_data['amount'],
                trade_data['commission'],
                trade_data['stamp_tax'],
                trade_data['net_amount'],
                trade_data['total_assets_before'],
                trade_data['total_assets_after']
            ))
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"记录交易失败: {e}")
            if conn is not None:
                conn.close()
            return False
    
    def complete_training_session(self, username: str, session_id: str, completion_data: Dict) -> bool:
        """完成训练会话（即使一笔未交易也要落库，否则历史里看不到这次训练）"""
        conn = None
        try:
            self._init_user_history_db(username)
            db_path = self._get_user_db_path(username)
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 更新训练会话状态
            cursor.execute('''
                UPDATE training_sessions 
                SET end_date = ?, final_capital = ?, total_return = ?, max_drawdown = ?, 
                    total_trades = ?, trade_win_rate = ?, session_win_rate = ?, total_bars = ?, completed_bars = ?, 
                    status = ?, completed_at = ?
                WHERE session_id = ?
            ''', (
                completion_data['end_date'],
                completion_data['final_capital'],
                completion_data['total_return'],
                completion_data.get('max_drawdown', 0),
                completion_data['total_trades'],
                completion_data['trade_win_rate'],
                completion_data['session_win_rate'],
                completion_data.get('total_bars', 0),
                completion_data.get('completed_bars', 0),
                'completed',
                datetime.now().isoformat(),
                session_id
            ))
            
            # 更新用户统计
            self._update_user_statistics(cursor, username, completion_data)
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"完成训练会话失败: {e}")
            if conn is not None:
                conn.close()
            return False
    
    def _update_user_statistics(self, cursor, username: str, completion_data: Dict):
        """更新用户统计信息"""
        # 获取当前统计
        cursor.execute('''
            SELECT total_sessions, completed_sessions, total_trades, total_return_sum, 
                   best_return, worst_return, avg_trade_win_rate, avg_session_win_rate, total_commission_paid
            FROM user_statistics WHERE username = ?
        ''', (username,))
        
        result = cursor.fetchone()
        
        if result:
            # 更新现有统计
            total_sessions, completed_sessions, total_trades, total_return_sum, \
            best_return, worst_return, avg_trade_win_rate, avg_session_win_rate, total_commission_paid = result
            
            new_total_sessions = total_sessions + 1
            new_completed_sessions = completed_sessions + 1
            new_total_trades = total_trades + completion_data['total_trades']
            new_total_return_sum = total_return_sum + completion_data['total_return']
            new_best_return = max(best_return, completion_data['total_return'])
            new_worst_return = min(worst_return, completion_data['total_return'])
            new_avg_trade_win_rate = avg_trade_win_rate
            if new_total_trades > 0:
                new_avg_trade_win_rate = (avg_trade_win_rate * total_trades + completion_data['trade_win_rate']*completion_data['total_trades']) / new_total_trades
            new_avg_session_win_rate = (avg_session_win_rate * completed_sessions + completion_data[
                'session_win_rate']) / new_completed_sessions
            new_total_commission_paid = total_commission_paid + completion_data.get('total_commission', 0)
            
            cursor.execute('''
                UPDATE user_statistics 
                SET total_sessions = ?, completed_sessions = ?, total_trades = ?, 
                    total_return_sum = ?, best_return = ?, worst_return = ?, 
                    avg_trade_win_rate = ?, avg_session_win_rate = ?, total_commission_paid = ?, last_updated = ?
                WHERE username = ?
            ''', (
                new_total_sessions, new_completed_sessions, new_total_trades,
                new_total_return_sum, new_best_return, new_worst_return,
                new_avg_trade_win_rate, new_avg_session_win_rate, new_total_commission_paid, datetime.now().isoformat(),
                username
            ))
        else:
            # 创建新统计
            cursor.execute('''
                INSERT INTO user_statistics 
                (username, total_sessions, completed_sessions, total_trades, total_return_sum,
                 best_return, worst_return, avg_trade_win_rate, avg_session_win_rate, total_commission_paid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                username, 1, 1, completion_data['total_trades'], completion_data['total_return'],
                completion_data['total_return'], completion_data['total_return'],
                completion_data['trade_win_rate'], completion_data['session_win_rate'], completion_data.get('total_commission', 0)
            ))
    
    def get_user_statistics(self, username: str) -> Optional[Dict]:
        """获取用户统计信息"""
        try:
            db_path = self._get_user_db_path(username)
            if not os.path.exists(db_path):
                return None
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT total_sessions, completed_sessions, total_trades, total_return_sum,
                       best_return, worst_return, avg_trade_win_rate, avg_session_win_rate, total_commission_paid
                FROM user_statistics WHERE username = ?
            ''', (username,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                total_sessions, completed_sessions, total_trades, total_return_sum, \
                best_return, worst_return, avg_trade_win_rate, avg_session_win_rate, total_commission_paid = result
                
                avg_return = total_return_sum / completed_sessions if completed_sessions > 0 else 0
                success_rate = (completed_sessions / total_sessions) * 100 if total_sessions > 0 else 0
                
                return {
                    'total_sessions': total_sessions,
                    'completed_sessions': completed_sessions,
                    'success_rate': success_rate,
                    'total_trades': total_trades,
                    'avg_return': avg_return,
                    'best_return': best_return,
                    'worst_return': worst_return,
                    'avg_trade_win_rate': avg_trade_win_rate,
                    'avg_session_win_rate': avg_session_win_rate,
                    'total_commission_paid': total_commission_paid
                }
            
            return None
        except Exception as e:
            print(f"获取用户统计失败: {e}")
            return None
    
    def get_training_history(self, username: str, limit: int = 20) -> List[Dict]:
        """获取训练历史"""
        try:
            db_path = self._get_user_db_path(username)
            if not os.path.exists(db_path):
                return []
            self._init_user_history_db(username)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT s.session_id, s.stock_code, s.stock_name, s.start_date, s.end_date, s.mode,
                       s.initial_capital, s.final_capital, s.total_return, s.total_trades,
                       s.trade_win_rate, s.session_win_rate, s.status, s.created_at, s.completed_at,
                       s.max_drawdown,
                       CASE WHEN r.report_json IS NOT NULL THEN 1 ELSE 0 END,
                       CASE WHEN r.ai_analysis IS NOT NULL THEN 1 ELSE 0 END
                FROM training_sessions s
                LEFT JOIN session_reports r ON r.session_id = s.session_id
                ORDER BY s.created_at DESC
                LIMIT ?
            ''', (limit,))

            results = cursor.fetchall()
            conn.close()

            history = []
            for row in results:
                history.append({
                    'session_id': row[0],
                    'stock_code': row[1],
                    'stock_name': row[2],
                    'start_date': row[3],
                    'end_date': row[4],
                    'mode': row[5],
                    'initial_capital': row[6],
                    'final_capital': row[7],
                    'total_return': row[8],
                    'total_trades': row[9],
                    'trade_win_rate': row[10],
                    'session_win_rate': row[11],
                    'status': row[12],
                    'created_at': row[13],
                    'completed_at': row[14],
                    'max_drawdown': row[15] if row[15] is not None else 0,
                    'has_report': bool(row[16]),
                    'has_ai_analysis': bool(row[17])
                })

            return history
        except Exception as e:
            print(f"获取训练历史失败: {e}")
            return []
    
    def get_session_detail(self, username: str, session_id: str) -> Optional[Dict]:
        """获取训练会话详情"""
        try:
            db_path = self._get_user_db_path(username)
            if not os.path.exists(db_path):
                return None
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取会话基本信息
            cursor.execute('''
                SELECT * FROM training_sessions WHERE session_id = ?
            ''', (session_id,))
            
            session_info = cursor.fetchone()
            if not session_info:
                conn.close()
                return None
            
            # 获取bar历史
            cursor.execute('''
                SELECT * FROM bar_history WHERE session_id = ? ORDER BY bar_id
            ''', (session_id,))
            
            bar_history = cursor.fetchall()
            
            # 获取交易历史
            cursor.execute('''
                SELECT * FROM trade_history WHERE session_id = ? ORDER BY bar_id
            ''', (session_id,))
            
            trade_history = cursor.fetchall()
            
            conn.close()
            
            return {
                'session_info': session_info,
                'bar_history': bar_history,
                'trade_history': trade_history
            }
        except Exception as e:
            print(f"获取会话详情失败: {e}")
            return None
    
    def get_performance_analysis(self, username: str, days: int = 30) -> Dict:
        """获取用户表现分析"""
        try:
            db_path = self._get_user_db_path(username)
            if not os.path.exists(db_path):
                return {}
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 获取最近N天的训练记录
            cursor.execute('''
                SELECT total_return, total_trades, trade_win_rate, session_win_rate, created_at
                FROM training_sessions 
                WHERE status = 'completed' 
                AND datetime(created_at) >= datetime('now', '-{} days')
                ORDER BY created_at
            '''.format(days))
            
            recent_sessions = cursor.fetchall()
            
            # 获取最佳和最差表现
            cursor.execute('''
                SELECT MAX(total_return) as best, MIN(total_return) as worst,
                       AVG(total_return) as avg, COUNT(*) as total
                FROM training_sessions 
                WHERE status = 'completed'
            ''')
            
            performance_stats = cursor.fetchone()
            
            # 获取交易频率分析
            cursor.execute('''
                SELECT AVG(total_trades) as avg_trades, 
                       AVG(trade_win_rate) as avg_trade_win_rate
                FROM training_sessions 
                WHERE status = 'completed'
            ''')
            
            trading_stats = cursor.fetchone()
            
            conn.close()
            
            return {
                'recent_sessions': recent_sessions,
                'performance_stats': performance_stats,
                'trading_stats': trading_stats,
                'analysis_period_days': days
            }
        except Exception as e:
            print(f"获取表现分析失败: {e}")
            return {}
    
    def delete_session(self, username: str, session_id: str) -> bool:
        """删除训练会话"""
        try:
            db_path = self._get_user_db_path(username)
            if not os.path.exists(db_path):
                return False
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 先确认这条记录存在，避免重复删除也返回成功
            cursor.execute('SELECT COUNT(*) FROM training_sessions WHERE session_id = ?', (session_id,))
            if (cursor.fetchone() or [0])[0] == 0:
                conn.close()
                return False

            cursor.execute('DELETE FROM bar_history WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM trade_history WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM training_sessions WHERE session_id = ?', (session_id,))
            try:
                cursor.execute('DELETE FROM session_reports WHERE session_id = ?', (session_id,))
            except sqlite3.OperationalError:
                # 老库可能还没有 session_reports 表
                pass

            # 删掉记录后重算用户汇总，避免顶部「总训练次数 / 总收益」虚高
            try:
                cursor.execute('''
                    UPDATE user_statistics SET
                        total_sessions = (SELECT COUNT(*) FROM training_sessions),
                        completed_sessions = (SELECT COUNT(*) FROM training_sessions
                                              WHERE status IN ('completed', 'ended')),
                        total_trades = (SELECT COALESCE(SUM(total_trades), 0) FROM training_sessions),
                        total_return_sum = (SELECT COALESCE(SUM(total_return), 0) FROM training_sessions
                                            WHERE status IN ('completed', 'ended')),
                        best_return = (SELECT COALESCE(MAX(total_return), 0) FROM training_sessions),
                        worst_return = (SELECT COALESCE(MIN(total_return), 0) FROM training_sessions),
                        avg_session_win_rate = (SELECT COALESCE(AVG(session_win_rate), 0) FROM training_sessions
                                                WHERE status IN ('completed', 'ended')),
                        avg_trade_win_rate = (SELECT COALESCE(AVG(trade_win_rate), 0) FROM training_sessions
                                              WHERE status IN ('completed', 'ended'))
                    WHERE username = ?
                ''', (username,))
            except sqlite3.OperationalError:
                pass
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            print(f"删除会话失败: {e}")
            return False
    
    def save_report(self, username: str, session_id: str, report: Dict) -> bool:
        """保存复盘报告（含交易明细），便于之后在历史记录里重新打开"""
        try:
            if not session_id or not report:
                return False
            self._init_user_history_db(username)
            conn = sqlite3.connect(self._get_user_db_path(username))
            cursor = conn.cursor()
            payload = json.dumps(report, ensure_ascii=False, default=str)
            cursor.execute('''
                INSERT INTO session_reports (session_id, report_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    report_json = excluded.report_json,
                    updated_at = excluded.updated_at
            ''', (session_id, payload, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存复盘报告失败: {e}")
            return False

    def save_ai_analysis(self, username: str, session_id: str, text: str, model: str = '',
                         fill_reviews=None, key_trade_reviews=None, review_meta=None) -> bool:
        """保存 AI 复盘点评文本；给了结构化点评时一并落盘（绑定 session_id 防串）"""
        try:
            if not session_id or not text:
                return False
            self._init_user_history_db(username)
            conn = sqlite3.connect(self._get_user_db_path(username))
            cursor = conn.cursor()
            fill_json = json.dumps(fill_reviews, ensure_ascii=False) if fill_reviews is not None else None
            key_json = json.dumps(key_trade_reviews, ensure_ascii=False) if key_trade_reviews is not None else None
            meta_json = json.dumps(review_meta, ensure_ascii=False) if review_meta is not None else None
            now = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO session_reports
                    (session_id, ai_analysis, ai_model, ai_updated_at, updated_at,
                     fill_reviews_json, key_trade_reviews_json, review_meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    ai_analysis = excluded.ai_analysis,
                    ai_model = excluded.ai_model,
                    ai_updated_at = excluded.ai_updated_at,
                    updated_at = excluded.updated_at,
                    fill_reviews_json = COALESCE(excluded.fill_reviews_json, session_reports.fill_reviews_json),
                    key_trade_reviews_json = COALESCE(excluded.key_trade_reviews_json, session_reports.key_trade_reviews_json),
                    review_meta_json = COALESCE(excluded.review_meta_json, session_reports.review_meta_json)
            ''', (session_id, text, model, now, now, fill_json, key_json, meta_json))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存 AI 点评失败: {e}")
            return False

    def get_report_and_analysis(self, username: str, session_id: str) -> Dict:
        """读取保存的报告与 AI 点评"""
        result = {'report': None, 'ai_analysis': None, 'ai_model': None, 'ai_updated_at': None,
                  'fill_reviews': None, 'key_trade_reviews': None, 'review_meta': None}
        try:
            db_path = self._get_user_db_path(username)
            if not os.path.exists(db_path):
                return result
            self._init_user_history_db(username)
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT report_json, ai_analysis, ai_model, ai_updated_at,
                       fill_reviews_json, key_trade_reviews_json, review_meta_json
                FROM session_reports WHERE session_id = ?
            ''', (session_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                if row[0]:
                    try:
                        result['report'] = json.loads(row[0])
                    except Exception:
                        result['report'] = None
                result['ai_analysis'] = row[1]
                result['ai_model'] = row[2]
                result['ai_updated_at'] = row[3]
                for key, idx in (('fill_reviews', 4), ('key_trade_reviews', 5), ('review_meta', 6)):
                    if len(row) > idx and row[idx]:
                        try:
                            result[key] = json.loads(row[idx])
                        except Exception:
                            result[key] = None
            return result
        except Exception as e:
            print(f"读取报告失败: {e}")
            return result

    def get_saved_ai_analysis(self, username: str, session_id: str) -> Optional[str]:
        try:
            return self.get_report_and_analysis(username, session_id).get('ai_analysis')
        except Exception:
            return None

    def export_session_data(self, username: str, session_id: str, format: str = 'json') -> Optional[str]:
        """导出训练会话数据"""
        try:
            session_detail = self.get_session_detail(username, session_id)
            if not session_detail:
                return None
            
            if format == 'json':
                return json.dumps(session_detail, indent=2, default=str)
            elif format == 'csv':
                # 这里可以实现CSV导出逻辑
                pass
            
            return None
        except Exception as e:
            print(f"导出会话数据失败: {e}")
            return None

