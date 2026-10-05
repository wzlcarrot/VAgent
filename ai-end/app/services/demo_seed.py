"""本仓独立演示：写入一条已索引视频，不依赖 ViewHub 上传回调。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _fill_missing_demo_vectors(cur) -> None:
    """演示块原先只写文本；向量为空时片内 vector_search 会得到 NULL 分并拖垮检索。"""
    try:
        cur.execute(
            """
            SELECT id, block_content FROM video_vector_block
            WHERE content_vector IS NULL
              AND video_id LIKE 'demo%%'
            ORDER BY id
            """
        )
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("demo seed 读取待嵌入块失败: %s", e)
        return
    if not isinstance(rows, (list, tuple)) or not rows:
        return
    ids: list = []
    texts: list = []
    for r in rows:
        if isinstance(r, dict):
            bid, text = r.get("id"), r.get("block_content")
        elif isinstance(r, (list, tuple)) and len(r) >= 2:
            bid, text = r[0], r[1]
        else:
            continue
        if bid is None or not text:
            continue
        ids.append(bid)
        texts.append(str(text))
    if not texts:
        return
    try:
        from app.tools.llm_tools import LLM_tools
        embeddings = LLM_tools.embed(texts)
    except Exception as e:
        logger.warning("demo seed embedding 失败: %s", e)
        return
    if not embeddings or len(embeddings) != len(ids):
        logger.warning("demo seed embedding 数量不匹配")
        return
    for bid, vec in zip(ids, embeddings, strict=False):
        vector_str = "[" + ",".join(str(v) for v in vec) + "]"
        cur.execute(
            "UPDATE video_vector_block SET content_vector = %s::vector WHERE id = %s",
            (vector_str, bid),
        )


_CHUNKS = (
    ("title_0", "Python 入门：变量、循环与函数", 0.0, 8.0),
    (
        "introduction_0",
        "本视频用三个例子讲 Python 入门：变量赋值、for 循环，以及如何定义函数。适合零基础。",
        8.0,
        40.0,
    ),
    (
        "subtitle_1_0",
        "首先看变量。在 Python 里用等号赋值，名字指向对象，没有类型声明。",
        12.0,
        28.0,
    ),
    (
        "subtitle_1_1",
        "接着是循环。for 可以遍历列表；range 用来重复固定次数。最后用 def 定义函数并 return。",
        28.0,
        55.0,
    ),
)


def seed_demo_corpus() -> None:
    from app.config import settings
    from app.tools.db.pool import get_global_pool

    if not settings.demo_seed_enabled:
        return
    pool = get_global_pool()
    if pool is None:
        logger.warning("demo seed 跳过：没有数据库")
        return
    vid = (settings.demo_video_id or "demo01").strip()
    conn = None
    try:
        conn = pool.getconn()
        cur = conn.cursor()
        for block_type, content, start_s, end_s in _CHUNKS:
            cur.execute(
                """
                INSERT INTO video_vector_block
                    (video_id, block_type, block_content, start_s, end_s)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (video_id, block_type) DO UPDATE SET
                    block_content = EXCLUDED.block_content,
                    start_s = EXCLUDED.start_s,
                    end_s = EXCLUDED.end_s
                """,
                (vid, block_type, content, start_s, end_s),
            )
        cur.execute("SAVEPOINT sp_demo_meta")
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_info (
                    user_id VARCHAR(64) PRIMARY KEY,
                    nick_name VARCHAR(64)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS video_info (
                    video_id VARCHAR(64) PRIMARY KEY,
                    video_cover VARCHAR(512),
                    video_name VARCHAR(256),
                    user_id VARCHAR(64),
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_update_time TIMESTAMP,
                    p_category_id INTEGER,
                    category_id INTEGER,
                    post_type INTEGER,
                    origin_info TEXT,
                    tags VARCHAR(256),
                    introduction TEXT,
                    interaction INTEGER,
                    duration INTEGER,
                    play_count INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0,
                    danmu_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    coin_count INTEGER DEFAULT 0,
                    collect_count INTEGER DEFAULT 0,
                    recommend_type INTEGER,
                    last_play_time TIMESTAMP
                )
                """
            )
            cur.execute(
                "INSERT INTO user_info (user_id, nick_name) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO NOTHING",
                ("demo_up", "演示UP"),
            )
            cur.execute(
                """
                INSERT INTO video_info (
                    video_id, video_name, user_id, tags, introduction, duration
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (video_id) DO UPDATE SET
                    video_name = EXCLUDED.video_name,
                    introduction = EXCLUDED.introduction,
                    tags = EXCLUDED.tags
                """,
                (
                    vid,
                    "Python 入门：变量、循环与函数",
                    "demo_up",
                    "Python,入门,编程",
                    "本视频用三个例子讲 Python 入门。",
                    8,
                ),
            )
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT sp_demo_meta")
            logger.warning("demo seed 元数据表跳过（可能已是 ViewHub 表结构）: %s", e)

        cur.execute("SAVEPOINT sp_demo_behavior")
        try:
            cur.execute("ALTER TABLE user_info ADD COLUMN IF NOT EXISTS email VARCHAR(128)")
            cur.execute("ALTER TABLE user_info ADD COLUMN IF NOT EXISTS password VARCHAR(256)")
            cur.execute("ALTER TABLE user_info ADD COLUMN IF NOT EXISTS avatar VARCHAR(512)")
            cur.execute("ALTER TABLE user_info ADD COLUMN IF NOT EXISTS current_coin_count INTEGER DEFAULT 0")
            cur.execute(
                """
                INSERT INTO user_info (user_id, nick_name, email, current_coin_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    nick_name = EXCLUDED.nick_name,
                    current_coin_count = EXCLUDED.current_coin_count
                """,
                ("demo_user", "演示用户", "demo@vagent.local", 42),
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_action (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    video_id VARCHAR(64) NOT NULL,
                    action_type INTEGER NOT NULL,
                    action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS video_play_history (
                    user_id VARCHAR(64) NOT NULL,
                    video_id VARCHAR(64) NOT NULL,
                    file_index INTEGER DEFAULT 1,
                    last_update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, video_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_focus (
                    user_id VARCHAR(64) NOT NULL,
                    focus_user_id VARCHAR(64) NOT NULL,
                    focus_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, focus_user_id)
                )
                """
            )
            extra = [
                ("demo02", "Python 列表与字典", "Python,进阶", "用几个例子讲 list 和 dict 的常用写法。"),
                ("demo03", "周末影评：一部入门纪录片", "纪录片,入门", "怎么从镜头和旁白读懂一部纪录片。"),
                ("demo04", "机器学习 10 分钟扫盲", "机器学习,入门", "监督学习和特征从哪来。"),
                ("demo05", "Vue 3 组件通信", "Vue,前端", "props、emits 与 provide/inject。"),
                ("demo06", "FastAPI 入门路由", "Python,后端", "path 参数、依赖注入和 OpenAPI。"),
                ("demo07", "Postgres 索引怎么选", "数据库,Postgres", "BTree 和 GIN 各适合什么查询。"),
                ("demo08", "Redis 缓存雪崩", "Redis,后端", "过期打散、互斥重建和降级。"),
                ("demo09", "HTTP 缓存协商", "网络,HTTP", "ETag 与 Cache-Control 怎么配合。"),
                ("demo10", "Git 变基与冲突", "Git,工程", "rebase 何时用、冲突怎么拆。"),
                ("demo11", "Linux 进程与信号", "Linux,系统", "僵尸进程、SIGTERM 与优雅退出。"),
                ("demo12", "推荐系统冷启动", "推荐,算法", "没有历史时用热门和标签兜底。"),
            ]
            for extra_id, name, tags, intro in extra:
                cur.execute(
                    """
                    INSERT INTO video_info (video_id, video_name, user_id, tags, introduction, duration, like_count, play_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (video_id) DO NOTHING
                    """,
                    (extra_id, name, "demo_up", tags, intro, 6, 12, 40),
                )
                cur.execute(
                    """
                    INSERT INTO video_vector_block (video_id, block_type, block_content, start_s, end_s)
                    VALUES (%s, 'title_0', %s, 0, 5)
                    ON CONFLICT (video_id, block_type) DO NOTHING
                    """,
                    (extra_id, name),
                )
                cur.execute(
                    """
                    INSERT INTO video_vector_block (video_id, block_type, block_content, start_s, end_s)
                    VALUES (%s, 'introduction_0', %s, 5, 40)
                    ON CONFLICT (video_id, block_type) DO NOTHING
                    """,
                    (extra_id, intro),
                )
            cur.execute("DELETE FROM user_action WHERE user_id = %s", ("demo_user",))
            cur.execute(
                "INSERT INTO user_action (user_id, video_id, action_type, action_time) VALUES "
                "(%s, %s, 2, CURRENT_TIMESTAMP), (%s, %s, 3, CURRENT_TIMESTAMP), "
                "(%s, %s, 2, CURRENT_TIMESTAMP), (%s, %s, 2, CURRENT_TIMESTAMP)",
                ("demo_user", vid, "demo_user", vid, "demo_user", "demo04", "demo_user", "demo06"),
            )
            cur.execute(
                """
                INSERT INTO video_play_history (user_id, video_id, file_index, last_update_time)
                VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, video_id) DO UPDATE SET last_update_time = CURRENT_TIMESTAMP
                """,
                ("demo_user", vid),
            )
            cur.execute(
                """
                INSERT INTO user_focus (user_id, focus_user_id, focus_time)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, focus_user_id) DO NOTHING
                """,
                ("demo_user", "demo_up"),
            )
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT sp_demo_behavior")
            logger.warning("demo seed 个人数据/推荐表跳过: %s", e)
        _fill_missing_demo_vectors(cur)
        conn.commit()
        cur.close()
        logger.info("demo seed 完成 video_id=%s", vid)
    except Exception as e:
        logger.warning("demo seed 失败: %s", e)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn is not None:
            pool.putconn(conn)
