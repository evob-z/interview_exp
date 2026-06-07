"""question_bank.py 语义匹配单元测试。"""

import numpy as np
import pytest


# ────────── fixture：每个测试前重置全局 embedding 模型状态 ──────────

@pytest.fixture(autouse=True)
def _reset_embedding_global():
    """确保每个测试的全局 _embedding_model 从干净状态开始。"""
    import knowledge.question_bank as qb_mod
    qb_mod._embedding_model = None
    yield
    qb_mod._embedding_model = None


# ────────── 辅助：构建 mock 题目 ──────────

def _make_q(qid: int, text: str, body: str = "") -> dict:
    """构造与 _parse_md 产出一致的题目 dict。"""
    return {
        "id": qid,
        "text": text,
        "category": "八股",
        "source": "",
        "points": [],
        "speech": "",
        "raw_body": body or f"要点：{text}",
    }


# ────────── 纯关键词匹配（无语义模型时降级） ──────────

def test_compute_score_exact_match():
    """精确子串命中 → score ≥ 10"""
    import knowledge.question_bank as qb_mod
    qb_mod._embedding_model = False  # 禁用语义
    from knowledge.question_bank import QuestionBank
    qb = QuestionBank.__new__(QuestionBank)
    qb._embeddings = {}

    score = qb._compute_score("agent的框架", _make_q(1, "agent的框架是什么"))
    assert score >= 10.0


def test_compute_score_reverse_match():
    """题库题目是用户输入的子串 → score ≥ 9"""
    import knowledge.question_bank as qb_mod
    qb_mod._embedding_model = False  # 禁用语义
    from knowledge.question_bank import QuestionBank
    qb = QuestionBank.__new__(QuestionBank)
    qb._embeddings = {}

    score = qb._compute_score("transformer是什么", _make_q(1, "Transformer"))
    assert 9.0 <= score < 10.0


def test_compute_score_ngram_only():
    """纯 n-gram 匹配（无语义）→ score < 10"""
    import knowledge.question_bank as qb_mod
    qb_mod._embedding_model = False  # 禁用语义
    from knowledge.question_bank import QuestionBank
    qb = QuestionBank.__new__(QuestionBank)
    qb._embeddings = {}

    score = qb._compute_score("agent的框架", _make_q(1, "如何评估 Agent 可靠性？"))
    assert score < 9.5


def test_compute_score_body_match():
    """正文精确匹配 → 额外 +5"""
    import knowledge.question_bank as qb_mod
    qb_mod._embedding_model = False  # 禁用语义
    from knowledge.question_bank import QuestionBank
    qb = QuestionBank.__new__(QuestionBank)
    qb._embeddings = {}

    score = qb._compute_score(
        "kubernetes",
        _make_q(1, "容器编排", body="要点：Kubernetes 是 Google 开源的容器编排平台"),
    )
    assert score >= 5.0


# ────────── 语义匹配（mock embedding） ──────────

class _MockEmbeddingModel:
    """伪造的 embedding 模型：对完全相同的文本返回相同向量，不同文本接近正交。"""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.encode_call_count = 0
        # 预生成一组正交基向量，按文本 hash 分配
        self._basis: dict[int, np.ndarray] = {}

    def _get_vec(self, text: str) -> np.ndarray:
        key = hash(text)
        if key not in self._basis:
            rng = np.random.RandomState(abs(key) % (2**31))
            vec = rng.randn(self.dim).astype(np.float32)
            vec = vec / np.linalg.norm(vec)
            self._basis[key] = vec
        return self._basis[key]

    def encode(self, texts, convert_to_numpy=True, show_progress_bar=False):
        self.encode_call_count += 1
        if isinstance(texts, str):
            texts = [texts]
        result = np.stack([self._get_vec(t) for t in texts])
        if len(texts) == 1 and not isinstance(texts, (list, np.ndarray)):
            return result[0]
        return result


def test_hybrid_score_distinguishes_bad_case():
    """语义匹配应区分 'agent框架' 和 'Agent可靠性评估'"""
    import knowledge.question_bank as qb_mod
    mock_model = _MockEmbeddingModel()
    qb_mod._embedding_model = mock_model

    from knowledge.question_bank import QuestionBank

    qb = QuestionBank.__new__(QuestionBank)

    qb.questions = [
        _make_q(1, "如何评估 Agent 可靠性？"),
        _make_q(2, "Agent 框架设计原则"),
    ]
    qb._embeddings = {}
    qb._compute_embeddings()
    assert len(qb._embeddings) == 2

    score_bad = qb._compute_score("agent的框架", qb.questions[0])
    score_good = qb._compute_score("agent的框架", qb.questions[1])

    assert score_good > score_bad, (
        f"语义匹配失败: 框架题得分 {score_good:.2f} ≤ 可靠性评估题 {score_bad:.2f}"
    )


def test_hybrid_score_exact_plus_semantic():
    """精确匹配 + 语义加成 → 强信号"""
    import knowledge.question_bank as qb_mod
    mock_model = _MockEmbeddingModel()
    qb_mod._embedding_model = mock_model

    from knowledge.question_bank import QuestionBank

    qb = QuestionBank.__new__(QuestionBank)
    qb.questions = [_make_q(1, "HTTP 和 HTTPS 的区别")]
    qb._embeddings = {}
    qb._compute_embeddings()

    score = qb._compute_score("http 和 https 的区别", qb.questions[0])
    assert score >= 14.0, f"精确+语义期望≥14，实际 {score:.2f}"


def test_hybrid_score_unrelated_semantic_near_zero():
    """两个完全无关的问题，语义相似度应接近 0，总分不应触发直接匹配"""
    import knowledge.question_bank as qb_mod
    mock_model = _MockEmbeddingModel()
    qb_mod._embedding_model = mock_model

    from knowledge.question_bank import QuestionBank

    qb = QuestionBank.__new__(QuestionBank)
    qb.questions = [_make_q(1, "Kubernetes Pod 调度策略")]
    qb._embeddings = {}
    qb._compute_embeddings()

    sem = qb._semantic_score("前端 React Hooks 原理", qb.questions[0])
    assert sem is not None
    assert sem < 0.3, f"无关问题语义相似度 {sem:.3f}，应接近 0"


def test_semantic_score_graceful_degradation():
    """语义模型不可用时应返回 None，不影响关键词评分"""
    import knowledge.question_bank as qb_mod
    qb_mod._embedding_model = False  # 模拟加载失败
    from knowledge.question_bank import QuestionBank

    qb = QuestionBank.__new__(QuestionBank)
    qb._embeddings = {}

    assert qb._semantic_score("test", _make_q(1, "test question")) is None


def test_load_computes_embeddings(isolated_repo):
    """load() 应触发 embedding 预计算"""
    import knowledge.question_bank as qb_mod
    mock_model = _MockEmbeddingModel()
    qb_mod._embedding_model = mock_model

    from knowledge.question_bank import QuestionBank

    bank_dir = isolated_repo / "问题库"
    bank_dir.mkdir(parents=True, exist_ok=True)
    (bank_dir / "test.md").write_text(
        "## Q1：agent框架设计\n要点：略\n\n## Q2：Agent可靠性评估\n要点：略\n",
        encoding="utf-8",
    )

    qb = QuestionBank(str(bank_dir))
    qb.load()

    assert len(qb.questions) == 2
    assert len(qb._embeddings) == 2
    assert mock_model.encode_call_count == 1
