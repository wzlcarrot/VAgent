"""
Schema 初始化

生产环境应改用 Alembic 迁移；当前保留为开发期快速启动。
所有 CREATE TABLE 都是 IF NOT EXISTS，幂等。
"""
import logging
from app.tools.db.pool import get_global_pool

logger = logging.getLogger(__name__)


def init_agent_tables():
    """启动时初始化 Agent 所需的表和数据"""
    pool = get_global_pool()
    if pool is None:
        logger.warning("数据库不可用，跳过初始化")
        return
    conn = None
    try:
        conn = pool.getconn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS platform_docs (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                type VARCHAR(50) DEFAULT 'faq',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        # pg_search（ParadeDB BM25）：与 init.sql 保持一致，确保任意初始化路径都有该扩展
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
        except Exception as e:
            logger.warning(f"pg_search 扩展不可用（BM25 将降级到 tsvector）: {e}")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_vector_block (
                id SERIAL PRIMARY KEY,
                video_id VARCHAR(64) NOT NULL,
                block_type VARCHAR(32) NOT NULL,
                block_content TEXT NOT NULL,
                content_vector vector(384),
                block_weight INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (video_id, block_type)
            )
        """)

        cursor.execute("SELECT COUNT(*) FROM platform_docs")
        count = cursor.fetchone()[0]
        if count == 0:
            docs = [
                ("ViewHub 是什么", "ViewHub 是一个视频分享平台，支持视频上传、播放、弹幕互动、评论交流等功能。你可以在这里找到各种有趣的视频内容。", "faq"),
                ("如何注册账号", "点击登录弹窗的「注册」标签，填写邮箱、昵称、密码，通过邮箱验证码完成注册。", "guide"),
                ("如何发布视频", "登录后点击右上角头像，选择「发布视频」。填写视频标题、简介、标签等信息，上传视频文件后提交。", "guide"),
                ("AI 助手能做什么", "ViewHub AI 助手可以回答关于视频内容的问题、推荐你感兴趣的视频、查询你的个人数据（播放历史、点赞收藏等），以及解答平台使用问题。", "faq"),
                ("如何点赞和收藏", "在视频播放页面，点击「点赞」按钮可以给视频点赞，点击「收藏」按钮可以把视频加入收藏夹。", "guide"),
                ("如何发送弹幕", "在视频播放页面，下方有弹幕输入框。输入你想说的话，点击发送即可。", "guide"),
                ("支持哪些功能", "ViewHub 支持视频上传与播放、弹幕互动、点赞收藏、评论交流、关注 UP 主、播放历史、AI 智能问答等功能。", "faq"),
            ]
            cursor.executemany(
                "INSERT INTO platform_docs (title, content, type) VALUES (%s, %s, %s)",
                docs
            )
            logger.info(f"platform_docs 表已初始化，插入 {len(docs)} 条数据")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_memory (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(64) NOT NULL,
                type VARCHAR(32) NOT NULL DEFAULT 'preference',
                content TEXT NOT NULL,
                source VARCHAR(32) DEFAULT 'inferred',
                score REAL DEFAULT 1.0,
                tags TEXT[] DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_user_id ON user_memory(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON user_memory(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_score ON user_memory(score DESC)")
        # pg_trgm GIN 索引：让 memory 的 ILIKE 关键词查询走索引，避免全表扫描
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_content_trgm "
                "ON user_memory USING gin (content gin_trgm_ops)"
            )
        except Exception as e:
            # pg_trgm 不可用时降级到普通 ILIKE（功能 OK 但慢）
            logger.warning(f"pg_trgm 索引创建失败，降级到 ILIKE 全表扫描: {e}")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(64),
                question TEXT NOT NULL,
                answer TEXT,
                session_id VARCHAR(64),
                image_urls TEXT[] DEFAULT '{}',
                videos JSONB DEFAULT '[]',
                reasons JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 兼容已存在但缺列的旧表（幂等）
        cursor.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS videos JSONB DEFAULT '[]'")
        cursor.execute("ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS reasons JSONB DEFAULT '[]'")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_user_id ON chat_history(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_session_id ON chat_history(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_created_at ON chat_history(created_at DESC)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                id BIGSERIAL PRIMARY KEY,
                checkpoint_id VARCHAR(64) NOT NULL,
                session_id VARCHAR(64) NOT NULL,
                workflow_type VARCHAR(64) NOT NULL,
                step_name VARCHAR(64) NOT NULL,
                state_snapshot JSONB NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'completed',
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (session_id, workflow_type, step_name)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_session ON workflow_checkpoints(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_workflow ON workflow_checkpoints(session_id, workflow_type)")
        # get_last_completed 按 created_at DESC 查询，加索引避免全表扫描
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoint_created_at ON workflow_checkpoints(created_at DESC)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_artifacts (
                id BIGSERIAL PRIMARY KEY,
                call_id VARCHAR(64) NOT NULL,
                session_id VARCHAR(64) NOT NULL,
                workflow_type VARCHAR(64) NOT NULL,
                artifact_type VARCHAR(32) NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifact_session ON run_artifacts(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifact_type ON run_artifacts(artifact_type)")

        conn.commit()
        cursor.close()
        logger.info("Agent 数据库初始化完成")

        # 预热 FAQ 缓存（避免首请求穿透到 DB）
        try:
            from app.tools.rag_tools import get_faq_cache
            cached = get_faq_cache(refresh=True)
            logger.info(f"FAQ 缓存预热完成，共 {len(cached)} 条")
        except Exception as e:
            logger.warning(f"FAQ 缓存预热失败: {e}")
    except Exception as e:
        logger.error(f"Agent 数据库初始化失败: {e}")
    finally:
        if conn:
            pool.putconn(conn)
