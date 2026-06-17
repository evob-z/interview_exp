"""
project_reader.py - 渐进式分层项目理解读取器

支持两种模式：
1. 自动发现模式：自动扫描项目目录，按层级发现文档
2. 手动配置模式：从 config 字符串读取指定文件（向后兼容）

分层结构（4层）：
- Tier 1: AI 工具总结（.qoder/repowiki, .cursor/rules, .cursorrules, .rules）
- Tier 2: 设计文档（README, ARCHITECTURE, docs/, spec/）
- Tier 3: 零散文档（根目录下其他 .md 文件）
- Tier 4: 代码文件（需用户批准，默认锁定）

加载策略：
- 启动时加载：Tier 1 + Tier 2
- 按需加载：Tier 3（搜索时触发）
- 锁定：Tier 4（标记存在但不读取）
"""

import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 单个文件最大读取字节数（100KB）
MAX_FILE_SIZE = 100 * 1024


@dataclass
class DocTier:
    """文档层级"""
    tier: int           # 1-4
    name: str           # "AI工具总结" / "设计文档" / "零散文档" / "代码"
    files: list = field(default_factory=list)  # [{path, content, size}]
    loaded: bool = False


class ProjectReader:
    """渐进式项目理解读取器

    支持两种模式：
    1. 自动发现模式：自动扫描项目目录，按层级发现文档
    2. 手动配置模式：从 config 字符串读取指定文件（向后兼容）

    加载策略：
    - 启动时：加载 Tier 1 + Tier 2
    - 按需：Tier 3 在搜索时加载
    - 锁定：Tier 4 需用户批准
    """

    # AI 工具目录名（Tier 1 自动发现）
    AI_TOOL_DIRS = [
        '.qoder/repowiki',
        '.cursor/rules',
        '.cursor',
    ]
    AI_TOOL_FILES = [
        '.cursorrules',
        '.rules',
    ]

    # 设计文档（Tier 2 自动发现）
    DESIGN_FILENAMES = [
        'README.md', 'readme.md',
        'ARCHITECTURE.md', 'DESIGN.md',
        'CONTRIBUTING.md', 'CHANGELOG.md',
    ]
    DESIGN_DIRS = ['docs', 'doc', 'spec', 'design']

    # 排除目录
    EXCLUDED_DIRS = {
        'node_modules', '.venv', 'venv', '__pycache__', '.git',
        '.idea', '.vscode', 'dist', 'build', '.tox', 'egg-info',
    }

    # 代码文件扩展名（Tier 4，锁定）
    CODE_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.go', '.rs', '.cpp', '.c', '.h'}

    TIER_NAMES = {
        1: "AI工具总结",
        2: "设计文档",
        3: "零散文档",
        4: "代码",
    }

    def __init__(self, config_str: str = "", projects: list[dict] = None):
        """
        Args:
            config_str: 向后兼容的配置字符串（格式：项目名:路径:文件1,文件2;...）
            projects: 直接传入项目列表 [{name, path}]，优先于 config_str
        """
        self._projects = []      # [{name, path}]
        self._tiers = {}         # {project_name: {1: DocTier, 2: DocTier, 3: DocTier, 4: DocTier}}
        self._manual_files = {}  # {project_name: [指定文件列表]} 手动覆盖
        self._code_approved = {} # {project_name: set(文件路径)} 用户批准的代码文件
        self._legacy_doc_files = {}  # {project_name: [doc_files]} 向后兼容

        # 解析配置
        if projects:
            self._projects = projects
        elif config_str:
            self._projects = self._parse_config(config_str)

    def _parse_config(self, config_str: str) -> list[dict]:
        """解析向后兼容的配置字符串
        格式：项目名:路径:文件1,文件2;项目名2:路径2:文件
        注意 Windows 盘符中的冒号
        """
        projects = []
        if not config_str.strip():
            return projects

        project_entries = config_str.strip().split(";")
        for entry in project_entries:
            entry = entry.strip()
            if not entry:
                continue

            parts = entry.split(":")
            # 处理 Windows 路径中的盘符冒号（如 D:/path）
            # 格式：项目名:盘符:/路径:文档文件
            if len(parts) >= 4 and len(parts[1]) == 1 and parts[1].isalpha():
                name = parts[0].strip()
                path = f"{parts[1]}:{parts[2]}".strip()
                doc_files_str = parts[3].strip() if len(parts) > 3 else ""
            elif len(parts) >= 3:
                name = parts[0].strip()
                path = parts[1].strip()
                doc_files_str = parts[2].strip()
            else:
                logger.warning(f"配置格式无效，跳过: {entry}")
                continue

            doc_files = [f.strip() for f in doc_files_str.split(",") if f.strip()]
            projects.append({"name": name, "path": path})
            self._legacy_doc_files[name] = doc_files

        return projects

    # ========== 自动发现 ==========

    def discover(self, project_name: str = None):
        """自动发现项目文档资源（不读取内容，只建立文件索引）

        Args:
            project_name: 指定项目名，None 则发现所有项目
        """
        targets = self._projects
        if project_name:
            targets = [p for p in self._projects if p['name'] == project_name]

        for proj in targets:
            name = proj['name']
            path = proj['path']
            if not os.path.isdir(path):
                logger.warning(f"项目路径不存在，跳过: {name} -> {path}")
                continue
            self._discover_project(name, path)

    def _discover_project(self, name: str, path: str):
        """发现单个项目的文档层级"""
        root = Path(path)

        # 初始化层级
        self._tiers[name] = {
            1: DocTier(tier=1, name=self.TIER_NAMES[1]),
            2: DocTier(tier=2, name=self.TIER_NAMES[2]),
            3: DocTier(tier=3, name=self.TIER_NAMES[3]),
            4: DocTier(tier=4, name=self.TIER_NAMES[4]),
        }

        # 跟踪已归类的文件，避免重复
        classified_files = set()

        # --- Tier 1: AI 工具目录 ---
        tier1_files = []

        # 扫描 AI 工具目录
        for dir_rel in self.AI_TOOL_DIRS:
            dir_path = root / dir_rel
            if dir_path.is_dir():
                for f in self._recursive_find_files(dir_path, extensions={'.md', '.txt', '.mdc'}):
                    rel = str(f.relative_to(root))
                    tier1_files.append({"path": rel, "abs_path": str(f), "content": None, "size": f.stat().st_size})
                    classified_files.add(rel.replace('\\', '/').lower())

        # 扫描 AI 工具单文件
        for fname in self.AI_TOOL_FILES:
            fpath = root / fname
            if fpath.is_file():
                rel = fname
                tier1_files.append({"path": rel, "abs_path": str(fpath), "content": None, "size": fpath.stat().st_size})
                classified_files.add(rel.replace('\\', '/').lower())

        self._tiers[name][1].files = tier1_files

        # --- Tier 2: 设计文档 ---
        tier2_files = []

        # 根目录下的设计文档
        for fname in self.DESIGN_FILENAMES:
            fpath = root / fname
            if fpath.is_file():
                rel = fname
                norm = rel.replace('\\', '/').lower()
                if norm not in classified_files:
                    tier2_files.append({"path": rel, "abs_path": str(fpath), "content": None, "size": fpath.stat().st_size})
                    classified_files.add(norm)

        # 设计文档目录
        for dir_name in self.DESIGN_DIRS:
            dir_path = root / dir_name
            if dir_path.is_dir():
                for f in self._recursive_find_files(dir_path, extensions={'.md', '.txt', '.rst'}):
                    rel = str(f.relative_to(root))
                    norm = rel.replace('\\', '/').lower()
                    if norm not in classified_files:
                        tier2_files.append({"path": rel, "abs_path": str(f), "content": None, "size": f.stat().st_size})
                        classified_files.add(norm)

        self._tiers[name][2].files = tier2_files

        # --- Tier 3: 零散文档 ---
        tier3_files = []

        # 扫描项目根目录下的 .md 文件（排除已归类的和排除目录下的）
        for f in self._find_root_md_files(root):
            rel = str(f.relative_to(root))
            norm = rel.replace('\\', '/').lower()
            if norm not in classified_files:
                tier3_files.append({"path": rel, "abs_path": str(f), "content": None, "size": f.stat().st_size})
                classified_files.add(norm)

        self._tiers[name][3].files = tier3_files

        # --- Tier 4: 代码文件（只标记存在，不列举所有文件） ---
        # 统计代码文件数量作为摘要
        code_count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            # 排除目录
            dirnames[:] = [d for d in dirnames if d not in self.EXCLUDED_DIRS]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in self.CODE_EXTENSIONS:
                    code_count += 1

        self._tiers[name][4].files = [{"count": code_count, "message": "代码文件需用户批准才能读取"}]

    def _recursive_find_files(self, directory: Path, extensions: set = None) -> list[Path]:
        """递归查找目录下的文件"""
        results = []
        try:
            for item in directory.rglob('*'):
                if item.is_file():
                    if extensions is None or item.suffix.lower() in extensions:
                        # 检查是否在排除目录中
                        parts = item.relative_to(directory).parts
                        if not any(part in self.EXCLUDED_DIRS for part in parts):
                            results.append(item)
        except PermissionError:
            logger.warning(f"权限不足，无法扫描: {directory}")
        except Exception as e:
            logger.warning(f"扫描目录失败 {directory}: {e}")
        return results

    def _find_root_md_files(self, root: Path) -> list[Path]:
        """查找根目录及浅层子目录中的 .md 文件（排除排除目录和设计目录）"""
        results = []
        excluded = self.EXCLUDED_DIRS | set(self.DESIGN_DIRS)
        # 加入 AI 工具目录的顶层部分
        ai_top_dirs = set()
        for d in self.AI_TOOL_DIRS:
            top = d.split('/')[0] if '/' in d else d
            ai_top_dirs.add(top)
        excluded = excluded | ai_top_dirs

        for dirpath, dirnames, filenames in os.walk(root):
            # 计算相对深度
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == '.' else len(Path(rel).parts)

            # 限制深度为 2 层（避免过深扫描）
            if depth > 2:
                dirnames.clear()
                continue

            # 排除目录
            dirnames[:] = [d for d in dirnames if d not in excluded]

            for fname in filenames:
                if fname.lower().endswith('.md'):
                    results.append(Path(dirpath) / fname)

        return results

    # ========== 加载 ==========

    def load_tier(self, project_name: str, tier: int) -> Optional[DocTier]:
        """加载指定层级的文档内容

        Args:
            project_name: 项目名
            tier: 层级号 (1-4)

        Returns:
            DocTier 对象，如果项目未发现则返回 None
        """
        if project_name not in self._tiers:
            logger.warning(f"项目未发现，请先调用 discover(): {project_name}")
            return None

        doc_tier = self._tiers[project_name].get(tier)
        if doc_tier is None:
            return None

        if doc_tier.loaded:
            return doc_tier

        # Tier 4 锁定，不自动加载
        if tier == 4:
            doc_tier.loaded = False
            return doc_tier

        # 读取文件内容
        for file_info in doc_tier.files:
            if 'abs_path' not in file_info:
                continue
            if file_info.get('content') is not None:
                continue

            abs_path = file_info['abs_path']
            try:
                content = self._read_file_content(abs_path)
                file_info['content'] = content
            except Exception as e:
                logger.warning(f"读取文件失败 {abs_path}: {e}")
                file_info['content'] = f"[读取失败: {e}]"

        doc_tier.loaded = True
        return doc_tier

    def _read_file_content(self, file_path: str) -> str:
        """读取文件内容，超过 MAX_FILE_SIZE 则截断"""
        size = os.path.getsize(file_path)
        encoding_list = ['utf-8', 'gbk', 'latin-1']

        for enc in encoding_list:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    if size > MAX_FILE_SIZE:
                        content = f.read(MAX_FILE_SIZE)
                        content += f"\n\n... [文件过大，已截断，原始大小: {size / 1024:.1f}KB] ..."
                    else:
                        content = f.read()
                return content
            except UnicodeDecodeError:
                continue
            except Exception as e:
                raise e

        return f"[无法解码文件: {file_path}]"

    def load_startup(self):
        """启动时加载：Tier 1 + Tier 2"""
        for proj in self._projects:
            name = proj['name']
            # 如果还没有 discover，先执行
            if name not in self._tiers:
                self.discover(name)
            self.load_tier(name, 1)
            self.load_tier(name, 2)

    # ========== 获取上下文 ==========

    def get_context(self, project_name: str, max_tier: int = 2) -> str:
        """获取项目理解上下文（用于注入 prompt）

        Args:
            project_name: 项目名
            max_tier: 最大读取到第几层（默认2，即 AI总结+设计文档）

        Returns:
            格式化的项目上下文文本
        """
        if project_name not in self._tiers:
            # 尝试使用手动文件（向后兼容）
            return self._get_legacy_context(project_name)

        lines = []
        proj_path = ""
        for p in self._projects:
            if p['name'] == project_name:
                proj_path = p.get('path', '')
                break

        lines.append(f"=== 项目: {project_name} ===")
        if proj_path:
            lines.append(f"路径: {proj_path}")
        lines.append("")

        for tier_num in range(1, max_tier + 1):
            doc_tier = self._tiers[project_name].get(tier_num)
            if doc_tier is None:
                continue

            # 确保已加载（Tier 3 按需加载）
            if not doc_tier.loaded and tier_num <= 3:
                self.load_tier(project_name, tier_num)

            if tier_num == 4:
                lines.append(f"--- [Tier 4: {doc_tier.name}] ---")
                lines.append("⚠️ 代码文件需用户批准才能读取")
                if doc_tier.files and 'count' in doc_tier.files[0]:
                    lines.append(f"共发现 {doc_tier.files[0]['count']} 个代码文件")
                lines.append("")
                continue

            if not doc_tier.files:
                continue

            lines.append(f"--- [Tier {tier_num}: {doc_tier.name}] ---")

            for file_info in doc_tier.files:
                if 'abs_path' not in file_info:
                    continue
                path = file_info.get('path', '')
                content = file_info.get('content', '')
                if content:
                    lines.append(f"### {path}")
                    lines.append(content)
                    lines.append("")

            lines.append("")

        return "\n".join(lines)

    def _get_legacy_context(self, project_name: str) -> str:
        """向后兼容：通过手动配置文件获取上下文"""
        result = self.read_project(project_name)
        if not result['docs']:
            return ""

        lines = [f"=== 项目: {project_name} ==="]
        if result['path']:
            lines.append(f"路径: {result['path']}")
        lines.append("")

        for doc in result['docs']:
            lines.append(f"### {doc['file']}")
            lines.append(doc['content'])
            lines.append("")

        return "\n".join(lines)

    def get_all_context(self, max_tier: int = 2) -> str:
        """获取所有项目的上下文"""
        contexts = []
        for proj in self._projects:
            ctx = self.get_context(proj['name'], max_tier=max_tier)
            if ctx:
                contexts.append(ctx)
        return "\n\n".join(contexts)

    # ========== 搜索 ==========

    def search_in_projects(self, query: str, max_tier: int = 3) -> list[dict]:
        """在项目文档中搜索关键词

        搜索时会按需加载 Tier 3（如果 Tier 1-2 没有足够结果）

        Args:
            query: 搜索关键词
            max_tier: 最大搜索层级

        Returns:
            [{project_name, tier, file, matched_content, context}]
        """
        if not query:
            return []

        query_lower = query.lower()
        results = []

        for proj in self._projects:
            name = proj['name']

            # 如果没有 discover，先执行
            if name not in self._tiers:
                self.discover(name)

            # 先搜索 Tier 1-2
            for tier_num in [1, 2]:
                tier_results = self._search_in_tier(name, tier_num, query_lower)
                results.extend(tier_results)

            # 如果结果不足 3 条且允许搜索 Tier 3，加载并搜索
            if len(results) < 3 and max_tier >= 3:
                self.load_tier(name, 3)
                tier_results = self._search_in_tier(name, 3, query_lower)
                results.extend(tier_results)

            # Tier 4：如果仍然不足，提示可能有代码文件
            if len(results) < 3 and max_tier >= 4:
                tier4 = self._tiers[name].get(4)
                if tier4 and tier4.files:
                    # 搜索已批准的代码文件
                    approved = self._code_approved.get(name, set())
                    if approved:
                        for fpath in approved:
                            try:
                                content = self._read_file_content(fpath)
                                if query_lower in content.lower():
                                    idx = content.lower().find(query_lower)
                                    context = self._extract_context(content, idx, len(query))
                                    results.append({
                                        "project_name": name,
                                        "tier": 4,
                                        "file": os.path.basename(fpath),
                                        "matched_content": content[idx:idx + len(query)],
                                        "context": context,
                                    })
                            except Exception:
                                pass
                    else:
                        # 未批准，给出提示
                        results.append({
                            "project_name": name,
                            "tier": 4,
                            "file": None,
                            "matched_content": None,
                            "context": None,
                            "message": "找到可能相关的代码文件，需要用户批准才能读取",
                            "files": [f"共 {tier4.files[0].get('count', '?')} 个代码文件"],
                        })

        return results

    def _search_in_tier(self, project_name: str, tier_num: int, query_lower: str) -> list[dict]:
        """在指定层级中搜索"""
        results = []
        doc_tier = self._tiers.get(project_name, {}).get(tier_num)
        if doc_tier is None or not doc_tier.loaded:
            return results

        for file_info in doc_tier.files:
            content = file_info.get('content', '')
            if not content:
                continue

            content_lower = content.lower()
            # 分词 OR 匹配：空格分隔的每个 token 任意命中即匹配
            # 中文查询无空格 → 等价原整串匹配；别名注入后多 token → 各自命中
            tokens = [t for t in query_lower.split() if len(t) >= 2]
            match_token = None
            for token in tokens:
                if token in content_lower:
                    match_token = token
                    break
            if match_token is None:
                continue

            idx = content_lower.find(match_token)
            context = self._extract_context(content, idx, len(match_token))
            results.append({
                "project_name": project_name,
                "tier": tier_num,
                "file": file_info.get('path', ''),
                "matched_content": content[idx:idx + len(match_token)],
                "context": context,
            })

        return results

    def _extract_context(self, content: str, idx: int, query_len: int, window: int = 150) -> str:
        """提取匹配上下文"""
        start = max(0, idx - window)
        end = min(len(content), idx + query_len + window)
        context = content[start:end]
        if start > 0:
            context = "..." + context
        if end < len(content):
            context = context + "..."
        return context

    # ========== 摘要 ==========

    def get_tier_summary(self, project_name: str) -> dict:
        """获取项目各层级文档摘要（文件数、已加载状态等）"""
        if project_name not in self._tiers:
            return {"error": f"项目未发现: {project_name}"}

        summary = {}
        for tier_num in range(1, 5):
            doc_tier = self._tiers[project_name].get(tier_num)
            if doc_tier is None:
                continue

            if tier_num == 4:
                count = doc_tier.files[0].get('count', 0) if doc_tier.files else 0
                summary[f"tier_{tier_num}"] = {
                    "name": doc_tier.name,
                    "file_count": count,
                    "loaded": False,
                    "locked": True,
                }
            else:
                summary[f"tier_{tier_num}"] = {
                    "name": doc_tier.name,
                    "file_count": len(doc_tier.files),
                    "loaded": doc_tier.loaded,
                    "files": [f.get('path', '') for f in doc_tier.files if 'path' in f],
                }

        return summary

    # ========== 向后兼容接口 ==========

    def read_project(self, project_name: str) -> dict:
        """向后兼容：读取指定项目的所有已加载文档
        Returns: {name, path, docs: [{file, content}]}
        """
        # 先尝试新的分层模式
        if project_name in self._tiers:
            docs = []
            for tier_num in [1, 2, 3]:
                doc_tier = self._tiers[project_name].get(tier_num)
                if doc_tier and doc_tier.loaded:
                    for file_info in doc_tier.files:
                        if file_info.get('content'):
                            docs.append({
                                "file": file_info.get('path', ''),
                                "content": file_info['content'],
                            })

            proj_path = ""
            for p in self._projects:
                if p['name'] == project_name:
                    proj_path = p.get('path', '')
                    break

            return {"name": project_name, "path": proj_path, "docs": docs}

        # 回退到手动配置模式
        project = None
        for p in self._projects:
            if p['name'] == project_name:
                project = p
                break

        if project is None:
            logger.warning(f"未找到项目: {project_name}")
            return {"name": project_name, "path": "", "docs": []}

        docs = []
        project_path = Path(project["path"])
        doc_files = self._legacy_doc_files.get(project_name, [])

        for doc_file in doc_files:
            file_path = project_path / doc_file
            try:
                if file_path.exists():
                    content = self._read_file_content(str(file_path))
                    docs.append({"file": doc_file, "content": content})
                else:
                    logger.warning(f"文档文件不存在，跳过: {file_path}")
            except Exception as e:
                logger.warning(f"读取文档失败 {file_path}: {e}")

        return {
            "name": project["name"],
            "path": project["path"],
            "docs": docs,
        }

    def read_all_projects(self) -> list[dict]:
        """向后兼容：读取所有项目"""
        results = []
        for project in self._projects:
            result = self.read_project(project["name"])
            results.append(result)
        return results

    # ========== 手动覆盖 ==========

    def add_manual_files(self, project_name: str, files: list[str]):
        """手动添加需要读取的文件（覆盖自动发现）

        Args:
            project_name: 项目名
            files: 文件相对路径列表
        """
        if project_name not in self._manual_files:
            self._manual_files[project_name] = []
        self._manual_files[project_name].extend(files)

        # 找到项目路径
        proj_path = None
        for p in self._projects:
            if p['name'] == project_name:
                proj_path = p.get('path', '')
                break

        if not proj_path:
            logger.warning(f"手动添加文件失败，未找到项目: {project_name}")
            return

        # 将手动文件加入 Tier 2（作为设计文档处理）
        if project_name not in self._tiers:
            self.discover(project_name)

        root = Path(proj_path)
        tier2 = self._tiers[project_name][2]
        for rel_file in files:
            abs_path = root / rel_file
            if abs_path.is_file():
                file_info = {
                    "path": rel_file,
                    "abs_path": str(abs_path),
                    "content": None,
                    "size": abs_path.stat().st_size,
                }
                # 避免重复
                existing_paths = {f.get('path') for f in tier2.files}
                if rel_file not in existing_paths:
                    tier2.files.append(file_info)
                    # 立即加载内容
                    try:
                        file_info['content'] = self._read_file_content(str(abs_path))
                    except Exception as e:
                        logger.warning(f"读取手动文件失败 {abs_path}: {e}")
            else:
                logger.warning(f"手动添加的文件不存在: {abs_path}")

    def set_code_approved(self, project_name: str, files: list[str]):
        """用户批准读取特定代码文件

        Args:
            project_name: 项目名
            files: 代码文件的绝对路径或相对路径列表
        """
        if project_name not in self._code_approved:
            self._code_approved[project_name] = set()

        proj_path = None
        for p in self._projects:
            if p['name'] == project_name:
                proj_path = p.get('path', '')
                break

        for f in files:
            if os.path.isabs(f):
                self._code_approved[project_name].add(f)
            elif proj_path:
                abs_path = str(Path(proj_path) / f)
                self._code_approved[project_name].add(abs_path)

    # ========== 兼容旧接口 ==========

    def parse_config(self) -> list[dict]:
        """向后兼容的 parse_config 方法"""
        results = []
        for p in self._projects:
            results.append({
                "name": p['name'],
                "path": p.get('path', ''),
                "doc_files": self._legacy_doc_files.get(p['name'], []),
            })
        return results
