import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def generate_html_report(
    username: str,
    results: List[Dict[str, Any]],
    stats: Dict[str, Any],
    output_path: str,
    title: Optional[str] = None,
) -> str:
    """
    Generate a self-contained, fully interactive HTML report using the exact
    styles and card layout of the Metis web interface.
    """
    base_dir = Path(__file__).parent.parent
    static_css_dir = base_dir / "static" / "css"

    style_css = ""
    username_css = ""

    if (static_css_dir / "style.css").exists():
        with open(static_css_dir / "style.css", "r", encoding="utf-8") as f:
            style_css = f.read()

    if (static_css_dir / "username.css").exists():
        with open(static_css_dir / "username.css", "r", encoding="utf-8") as f:
            username_css = f.read()

    import base64
    pattern_png_path = base_dir / "static" / "pattern.png"
    pattern_bg = ""
    if pattern_png_path.exists():
        try:
            with open(pattern_png_path, "rb") as pf:
                b64_img = base64.b64encode(pf.read()).decode("utf-8")
                pattern_bg = f"data:image/png;base64,{b64_img}"
        except Exception:
            pattern_bg = "/static/pattern.png"
    else:
        pattern_bg = "/static/pattern.png"

    report_title = title or f"Metis OSINT Report — {username}"
    generation_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Serialize results data safely for injection
    results_json = json.dumps(results, indent=None)
    stats_json = json.dumps(stats, indent=None)

    html_content = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_title}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    fontFamily: {{
                        mono: ['JetBrains Mono', 'monospace'],
                    }},
                }}
            }}
        }};
    </script>
    <style>
{style_css}

{username_css}

/* Extra report-specific overrides */
body {{
    background-color: #0b0c10;
}}
.report-badge {{
    background: rgba(139, 92, 246, 0.15);
    border: 1px solid rgba(139, 92, 246, 0.4);
    color: #c4b5fd;
}}
    </style>
</head>
<body class="bg-black text-white font-mono min-h-screen flex flex-col bg-[linear-gradient(rgba(0,0,0,.9),rgba(0,0,0,.9)),repeating-linear-gradient(0deg,transparent,transparent 39px,rgba(71,85,105,.1) 40px),repeating-linear-gradient(90deg,transparent,transparent 39px,rgba(71,85,105,.1) 40px)]">
    <div class="m_2ce0de02 opacity-90"
        style="z-index:-1; height:100%; background-repeat:repeat-y; background-image:url('{pattern_bg}'); position:fixed; width:100%; top:0; left:0;"></div>

    <!-- Header -->
    <header class="bg-[#1a1b26]/60 backdrop-blur-md border-b border-[#24283b] sticky top-0 z-40">
        <div class="max-w-6xl mx-auto px-4 py-4 md:px-6">
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                    <i class="fas fa-fingerprint text-2xl text-purple-400"></i>
                    <div>
                        <span class="text-xl font-bold tracking-tight text-white">Metis</span>
                        <span class="ml-2 text-xs uppercase px-2 py-0.5 rounded report-badge font-semibold">Report</span>
                    </div>
                </div>
                <div class="text-xs text-gray-400">
                    Generated: <span class="text-gray-300">{generation_time}</span>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="flex-grow">
        <div class="username-page mx-auto w-full max-w-6xl px-4 py-6 md:px-6">
            <div class="username-toolbar">
                <div class="username-title">
                    <div>
                        <h1>Target: <span class="text-purple-400">@{username}</span></h1>
                        <span class="text-sm text-gray-400">Search Report</span>
                    </div>
                    <span id="progressText">{len(results)} Found</span>
                </div>
            </div>

            <!-- Stats Overview -->
            <div class="username-status-row">
                <div class="username-stat">
                    <span>Scanned</span>
                    <strong id="sourcesScanned">{stats.get('total_checked', len(results))}</strong>
                </div>
                <div class="username-stat">
                    <span>Found</span>
                    <strong id="usernamesFound" class="text-green-400">{len(results)}</strong>
                </div>
                <div class="username-stat">
                    <span>Duration</span>
                    <strong>{stats.get('search_time_seconds', 'N/A')}s</strong>
                </div>
                <div class="username-stat">
                    <span>Success Rate</span>
                    <strong class="text-purple-400">{stats.get('success_rate', 'N/A')}%</strong>
                </div>
            </div>

            <!-- Controls (Flat / Grouped & Category Filter) -->
            <div class="username-controls">
                <div id="categoryStats" class="username-category-summary">
                    <div id="categoryStatsGrid"></div>
                </div>

                <div id="filterSection" class="username-view-controls">
                    <div class="username-segmented" aria-label="Result layout">
                        <button type="button" id="flatViewBtn" class="active" data-view="flat">
                            <i class="fas fa-border-all"></i>
                            <span>Flat</span>
                        </button>
                        <button type="button" id="groupedViewBtn" data-view="grouped">
                            <i class="fas fa-layer-group"></i>
                            <span>Grouped</span>
                        </button>
                    </div>
                    <select id="categoryFilter" class="hidden">
                        <option value="all">All Categories</option>
                    </select>
                </div>
            </div>

            <!-- Results shell -->
            <div id="resultsContainer" class="username-results-shell">
                <div id="resultsMasonry" class="username-masonry"></div>
                <div id="groupedResults" class="username-grouped hidden"></div>
            </div>
        </div>
    </main>

    <footer class="border-t border-[#24283b] py-4 text-center text-xs text-gray-500">
        Metis Username Intelligence Report
    </footer>

    <!-- Interactive Report Script -->
    <script>
        const INITIAL_RESULTS = {results_json};
        const INITIAL_STATS = {stats_json};

        class MetisReportViewer {{
            constructor(results) {{
                this.results = results || [];
                this.resultsByCategory = {{}};
                this.viewMode = 'flat';
                this.activeCategory = 'all';

                this.elements = {{
                    resultsContainer: document.getElementById('resultsContainer'),
                    resultsMasonry: document.getElementById('resultsMasonry'),
                    groupedResults: document.getElementById('groupedResults'),
                    categoryStatsGrid: document.getElementById('categoryStatsGrid'),
                    categoryFilter: document.getElementById('categoryFilter'),
                    flatViewBtn: document.getElementById('flatViewBtn'),
                    groupedViewBtn: document.getElementById('groupedViewBtn')
                }};

                this.indexResults();
                this.bindEvents();
                this.renderCategoryPills();
                this.render();
            }}

            indexResults() {{
                this.resultsByCategory = {{}};
                this.results.forEach(r => {{
                    const cat = r.category || 'unknown';
                    if (!this.resultsByCategory[cat]) {{
                        this.resultsByCategory[cat] = [];
                    }}
                    this.resultsByCategory[cat].push(r);
                }});
            }}

            bindEvents() {{
                if (this.elements.flatViewBtn) {{
                    this.elements.flatViewBtn.addEventListener('click', () => this.switchView('flat'));
                }}
                if (this.elements.groupedViewBtn) {{
                    this.elements.groupedViewBtn.addEventListener('click', () => this.switchView('grouped'));
                }}
                if (this.elements.categoryFilter) {{
                    this.elements.categoryFilter.addEventListener('change', (e) => this.filterByCategory(e.target.value));
                }}
            }}

            switchView(mode) {{
                this.viewMode = mode;
                this.elements.flatViewBtn.classList.toggle('active', mode === 'flat');
                this.elements.groupedViewBtn.classList.toggle('active', mode === 'grouped');
                this.elements.categoryFilter.classList.toggle('hidden', mode !== 'grouped');
                this.elements.resultsMasonry.classList.toggle('hidden', mode !== 'flat');
                this.elements.groupedResults.classList.toggle('hidden', mode !== 'grouped');
                this.render();
            }}

            filterByCategory(cat) {{
                this.activeCategory = cat;
                const sections = this.elements.groupedResults.querySelectorAll('[data-category]');
                sections.forEach(s => {{
                    if (cat === 'all' || s.dataset.category === cat) {{
                        s.style.display = 'block';
                    }} else {{
                        s.style.display = 'none';
                    }}
                }});
            }}

            renderCategoryPills() {{
                const categories = Object.keys(this.resultsByCategory).sort();
                this.elements.categoryStatsGrid.innerHTML = categories.map(cat => {{
                    const count = this.resultsByCategory[cat].length;
                    return `
                        <button type="button" class="username-category-pill" data-category="${{this.escapeHtml(cat)}}">
                            <span>${{this.escapeHtml(cat)}}</span>
                            <strong>${{count}}</strong>
                        </button>
                    `;
                }}).join('');

                this.elements.categoryStatsGrid.querySelectorAll('.username-category-pill').forEach(btn => {{
                    btn.addEventListener('click', () => {{
                        this.switchView('grouped');
                        this.filterByCategory(btn.dataset.category);
                        this.elements.categoryFilter.value = btn.dataset.category;
                    }});
                }});

                this.elements.categoryFilter.innerHTML = '<option value="all">All Categories</option>' +
                    categories.map(cat => `<option value="${{cat}}">${{cat.charAt(0).toUpperCase() + cat.slice(1)}}</option>`).join('');
            }}

            render() {{
                this.elements.resultsMasonry.innerHTML = '';
                this.elements.groupedResults.innerHTML = '';

                if (this.viewMode === 'grouped') {{
                    Object.keys(this.resultsByCategory).sort().forEach(cat => {{
                        const section = document.createElement('section');
                        section.className = 'username-category-section fade-in';
                        section.dataset.category = cat;
                        section.innerHTML = `
                            <div class="username-category-heading">
                                <h2>${{this.escapeHtml(cat)}}</h2>
                                <span class="category-count">${{this.resultsByCategory[cat].length}}</span>
                            </div>
                            <div class="username-category-results"></div>
                        `;
                        const grid = section.querySelector('.username-category-results');
                        this.resultsByCategory[cat].forEach(r => grid.appendChild(this.createCard(r)));
                        this.elements.groupedResults.appendChild(section);
                    }});
                    this.filterByCategory(this.activeCategory);
                }} else {{
                    this.results.forEach(r => {{
                        this.elements.resultsMasonry.appendChild(this.createCard(r));
                    }});
                }}
            }}

            getPlatformIcon(siteName, category) {{
                const name = (siteName || '').toLowerCase();
                if (name.includes('github')) return {{ class: 'github-green', icon: 'GH' }};
                if (name.includes('twitter') || name.includes('x.com')) return {{ class: 'twitter-blue', icon: '𝕏' }};
                if (name.includes('instagram')) return {{ class: 'instagram-gradient', icon: 'IG' }};
                if (name.includes('linkedin')) return {{ class: 'linkedin-blue', icon: 'in' }};
                if (name.includes('reddit')) return {{ class: 'reddit-orange', icon: 'R' }};
                if (name.includes('discord')) return {{ class: 'discord-purple', icon: 'D' }};
                if (name.includes('telegram')) return {{ class: 'telegram-blue', icon: 'TG' }};
                if (name.includes('snapchat')) return {{ class: 'snapchat-yellow', icon: 'SC' }};
                if (name.includes('mastodon')) return {{ class: 'mastodon-purple', icon: 'M' }};
                if (category === 'search engine' || name.includes('duckduckgo')) return {{ class: 'bg-amber-600', icon: '🦆' }};
                if (name.includes('steam')) return {{ class: 'steam-blue', icon: 'ST' }};
                if (name.includes('epic')) return {{ class: 'epic-black', icon: 'EG' }};
                if (name.includes('twitch')) return {{ class: 'twitch-purple', icon: 'TW' }};
                if (name.includes('spotify')) return {{ class: 'spotify-green', icon: '♪' }};
                if (name.includes('youtube')) return {{ class: 'youtube-red', icon: 'YT' }};
                if (name.includes('tiktok')) return {{ class: 'tiktok-black', icon: 'TT' }};
                if (name.includes('pinterest')) return {{ class: 'pinterest-red', icon: 'P' }};
                if (name.includes('vimeo')) return {{ class: 'vimeo-blue', icon: 'V' }};
                if (name.includes('gitlab')) return {{ class: 'gitlab-orange', icon: 'GL' }};
                if (name.includes('stackoverflow')) return {{ class: 'stackoverflow-orange', icon: 'SO' }};
                if (name.includes('patreon')) return {{ class: 'patreon-orange', icon: 'PT' }};

                const f = (siteName || 'S').charAt(0).toUpperCase();
                const s = (siteName && siteName.length > 1) ? siteName.charAt(1).toUpperCase() : '';
                return {{ class: 'bg-gray-700', icon: f + s }};
            }}

            extractKeyInfo(profileData) {{
                if (!profileData) return {{}};
                const info = {{
                    username: profileData.username || profileData.user_name || profileData.login || null,
                    fullName: profileData.fullname || profileData.full_name || profileData.name || null,
                    bio: profileData.bio || profileData.description || profileData.about || null,
                    profileImage: profileData.profileImageUrl || profileData.avatar_url || profileData.image || profileData.photo || null,
                    followers: profileData.followers || profileData.follower_count || null,
                    following: profileData.following || profileData.following_count || null,
                    posts: profileData.posts || profileData.statuses_count || null,
                    country: profileData.country || profileData.location || null,
                    website: profileData.website || profileData.blog || null,
                    createdAt: profileData.createdAt || profileData.created_at || null,
                }};
                if (typeof info.profileImage === 'object' && info.profileImage?.url) {{
                    info.profileImage = info.profileImage.url;
                }}
                return info;
            }}

            createCard(result) {{
                const platformInfo = this.getPlatformIcon(result.site_name, result.category);
                const keyInfo = this.extractKeyInfo(result.profile_data);
                const hasProfileData = result.profile_data && Object.keys(result.profile_data).length > 0;
                const domain = result.url ? new URL(result.url).hostname.replace(/^www\\./, '') : '';
                const faviconUrl = domain ? `https://www.google.com/s2/favicons?domain=${{encodeURIComponent(domain)}}&sz=128` : '';
                const profileImg = keyInfo.profileImage;

                const card = document.createElement('div');
                card.className = `result-card username-result-card fade-in${{profileImg ? ' has-profile-image' : ''}}`;
                card.dataset.url = result.url;
                card.dataset.site = result.site_name;

                card.innerHTML = `
                    <div class="username-card-header">
                        <div class="username-card-heading">
                            <div class="username-site-mark">
                                ${{faviconUrl ? `
                                    <img src="${{this.escapeHtml(faviconUrl)}}" alt="" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                                    <div class="platform-icon ${{platformInfo.class}} username-site-mark-fallback">${{this.escapeHtml(platformInfo.icon)}}</div>
                                ` : `
                                    <div class="platform-icon ${{platformInfo.class}}">${{this.escapeHtml(platformInfo.icon)}}</div>
                                `}}
                            </div>
                            <div class="username-card-title">
                                <h3 title="${{this.escapeHtml(result.site_name)}}">${{this.escapeHtml(result.site_name)}}</h3>
                                <span>${{this.escapeHtml(result.category || 'unknown')}}</span>
                            </div>
                        </div>
                        ${{profileImg ? `
                            <div class="username-card-media">
                                <button type="button" class="username-avatar-preview-btn" title="Preview avatar">
                                    <img src="${{this.escapeHtml(profileImg)}}" alt="" class="username-card-avatar" onerror="this.closest('.username-result-card').classList.remove('has-profile-image'); this.closest('.username-card-media').style.display='none';">
                                </button>
                                <div class="username-reverse-search">
                                    <a href="https://lens.google.com/uploadbyurl?url=${{encodeURIComponent(profileImg)}}" target="_blank" rel="noopener noreferrer" title="Google Lens">
                                        <i class="fab fa-google"></i>
                                    </a>
                                    <a href="https://yandex.com/images/search?rpt=imageview&url=${{encodeURIComponent(profileImg)}}" target="_blank" rel="noopener noreferrer" title="Yandex Search">
                                        <i class="fas fa-search"></i>
                                    </a>
                                </div>
                            </div>
                        ` : ''}}
                    </div>

                    ${{keyInfo.username ? `
                        <div class="username-handle-row">
                            <span>@${{this.escapeHtml(String(keyInfo.username))}}</span>
                            <button class="copy-username-btn" title="Copy username">
                                <i class="fas fa-copy"></i>
                            </button>
                        </div>
                    ` : ''}}

                    <div class="username-card-content">
                        ${{keyInfo.bio ? `<p class="username-card-bio">${{this.escapeHtml(String(keyInfo.bio))}}</p>` : ''}}
                        ${{keyInfo.fullName ? `
                            <div class="username-data-row">
                                <strong>Name</strong>
                                <span>${{this.escapeHtml(String(keyInfo.fullName))}}</span>
                            </div>
                        ` : ''}}
                        ${{keyInfo.country ? `
                            <div class="username-data-row">
                                <strong>Location</strong>
                                <span>${{this.escapeHtml(String(keyInfo.country))}}</span>
                            </div>
                        ` : ''}}
                        ${{keyInfo.followers ? `
                            <div class="username-data-row">
                                <strong>Followers</strong>
                                <span>${{this.escapeHtml(String(keyInfo.followers))}}</span>
                            </div>
                        ` : ''}}
                        ${{keyInfo.posts ? `
                            <div class="username-data-row">
                                <strong>Posts</strong>
                                <span>${{this.escapeHtml(String(keyInfo.posts))}}</span>
                            </div>
                        ` : ''}}
                    </div>

                    <div class="username-card-actions">
                        <a href="${{this.escapeHtml(result.url)}}" target="_blank" rel="noopener noreferrer">
                            <i class="fas fa-external-link-alt"></i>
                            <span>Visit Site</span>
                        </a>
                        ${{hasProfileData ? `
                            <button class="expand-btn text-purple-400 hover:text-purple-300">
                                <i class="fas fa-code"></i>
                                <span>JSON Data</span>
                            </button>
                        ` : ''}}
                    </div>
                `;

                const copyBtn = card.querySelector('.copy-username-btn');
                if (copyBtn && keyInfo.username) {{
                    copyBtn.addEventListener('click', () => {{
                        navigator.clipboard.writeText(keyInfo.username);
                        copyBtn.innerHTML = '<i class="fas fa-check text-green-400"></i>';
                        setTimeout(() => {{ copyBtn.innerHTML = '<i class="fas fa-copy"></i>'; }}, 1500);
                    }});
                }}

                const expandBtn = card.querySelector('.expand-btn');
                if (expandBtn) {{
                    expandBtn.addEventListener('click', () => this.showDataModal(result));
                }}

                const avatarBtn = card.querySelector('.username-avatar-preview-btn');
                if (avatarBtn && profileImg) {{
                    avatarBtn.addEventListener('click', () => this.showImageModal(profileImg, result.site_name));
                }}

                return card;
            }}

            showDataModal(result) {{
                const modal = document.createElement('div');
                modal.className = 'modal-overlay';
                modal.innerHTML = `
                    <div class="modal-content">
                        <div class="modal-header">
                            <div>
                                <h2 class="text-lg font-bold text-white">${{this.escapeHtml(result.site_name)}}</h2>
                                <p class="text-xs text-gray-400">Extracted Profile Data</p>
                            </div>
                            <button class="close-modal text-gray-400 hover:text-white p-2">
                                <i class="fas fa-times text-lg"></i>
                            </button>
                        </div>
                        <div class="modal-body">
                            <pre class="text-xs text-purple-300 bg-gray-950 p-4 rounded-lg overflow-x-auto">${{this.escapeHtml(JSON.stringify(result.profile_data, null, 2))}}</pre>
                        </div>
                        <div class="modal-footer">
                            <button class="copy-json-btn px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded text-sm flex items-center gap-2">
                                <i class="fas fa-copy"></i>
                                <span>Copy JSON</span>
                            </button>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
                const close = () => modal.remove();
                modal.querySelector('.close-modal').addEventListener('click', close);
                modal.addEventListener('click', (e) => {{ if (e.target === modal) close(); }});
                modal.querySelector('.copy-json-btn').addEventListener('click', (e) => {{
                    navigator.clipboard.writeText(JSON.stringify(result.profile_data, null, 2));
                    e.currentTarget.innerHTML = '<i class="fas fa-check"></i> Copied!';
                    setTimeout(() => {{ close(); }}, 1000);
                }});
            }}

            showImageModal(imgUrl, title) {{
                const modal = document.createElement('div');
                modal.className = 'modal-overlay username-image-preview-overlay';
                modal.innerHTML = `
                    <div class="username-image-preview-card">
                        <div class="username-image-preview-header">
                            <h2>${{this.escapeHtml(title || 'Avatar Preview')}}</h2>
                            <button type="button" class="close-modal"><i class="fas fa-times"></i></button>
                        </div>
                        <div class="username-image-preview-body">
                            <img src="${{this.escapeHtml(imgUrl)}}" alt="Avatar">
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
                const close = () => modal.remove();
                modal.querySelector('.close-modal').addEventListener('click', close);
                modal.addEventListener('click', (e) => {{ if (e.target === modal) close(); }});
            }}

            escapeHtml(text) {{
                if (text === null || text === undefined) return '';
                return String(text).replace(/[&<>"']/g, m => ({{
                    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
                }}[m]));
            }}
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            window.reportViewer = new MetisReportViewer(INITIAL_RESULTS);
        }});
    </script>
</body>
</html>
"""

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    return str(out_file.resolve())
