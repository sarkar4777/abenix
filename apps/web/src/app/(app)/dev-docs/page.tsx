'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Book, Search, Menu, X, ChevronRight } from 'lucide-react';
import 'highlight.js/styles/github-dark.css';

interface DocEntry { slug: string; title: string }
interface Section { id: string; title: string; docs: DocEntry[] }
interface Manifest { sections: Section[] }

const DOCS_BASE = '/dev-docs';

export default function DevDocsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const slug = params.get('slug') || 'README';

  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchIndex, setSearchIndex] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    fetch(`${DOCS_BASE}/manifest.json`).then((r) => r.json()).then(setManifest);
  }, []);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    fetch(`${DOCS_BASE}/${slug}.md`)
      .then((r) => (r.ok ? r.text() : Promise.reject(`HTTP ${r.status}`)))
      .then((md) => setContent(md))
      .catch(() => setContent(`# Not found\n\nThe page \`${slug}\` does not exist.`))
      .finally(() => setLoading(false));
  }, [slug]);

  // Build a one-time search index over every doc body.
  useEffect(() => {
    if (!manifest) return;
    if (searchIndex.size > 0) return;
    (async () => {
      const map = new Map<string, string>();
      for (const sec of manifest.sections) {
        for (const d of sec.docs) {
          try {
            const r = await fetch(`${DOCS_BASE}/${d.slug}.md`);
            if (r.ok) map.set(d.slug, (await r.text()).toLowerCase());
          } catch {}
        }
      }
      setSearchIndex(map);
    })();
  }, [manifest]);

  const searchHits = useMemo(() => {
    if (!query.trim() || !manifest) return null;
    const q = query.toLowerCase();
    const hits: Array<{ slug: string; title: string; section: string; snippet: string }> = [];
    for (const sec of manifest.sections) {
      for (const d of sec.docs) {
        const body = searchIndex.get(d.slug) || '';
        const titleMatch = d.title.toLowerCase().includes(q);
        const bodyIdx = body.indexOf(q);
        if (!titleMatch && bodyIdx < 0) continue;
        const start = Math.max(0, bodyIdx - 60);
        const end = Math.min(body.length, bodyIdx + 80);
        const snippet = bodyIdx >= 0
          ? '…' + body.slice(start, end).replace(/\s+/g, ' ') + '…'
          : '';
        hits.push({ slug: d.slug, title: d.title, section: sec.title, snippet });
      }
    }
    return hits.slice(0, 20);
  }, [query, manifest, searchIndex]);

  const navigate = (s: string) => {
    router.push(`/dev-docs?slug=${encodeURIComponent(s)}`);
    setSidebarOpen(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="-m-3 md:-m-6 flex min-h-[calc(100vh-3.5rem)] bg-[#0B0F19]">
      {/* Mobile sidebar toggle */}
      <button
        onClick={() => setSidebarOpen((v) => !v)}
        className="lg:hidden fixed top-20 left-3 z-30 p-2 rounded-lg bg-slate-800/80 border border-slate-700 text-slate-300"
        aria-label="Toggle sidebar"
      >
        {sidebarOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
      </button>

      {/* Sidebar */}
      <aside
        className={`fixed lg:sticky top-14 left-0 z-20 w-72 h-[calc(100vh-3.5rem)] bg-slate-900/95 lg:bg-slate-900/40 border-r border-slate-800 overflow-y-auto transition-transform ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="p-4 sticky top-0 bg-slate-900/95 backdrop-blur border-b border-slate-800 z-10">
          <div className="flex items-center gap-2 mb-3">
            <Book className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-bold text-white">Developer docs</h2>
          </div>
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full pl-7 pr-2 py-1.5 text-xs bg-slate-950/60 border border-slate-700 rounded text-white focus:outline-none focus:border-cyan-500"
              data-testid="devdocs-search"
            />
          </div>
        </div>

        {searchHits ? (
          <div className="p-3 space-y-1">
            <p className="text-[10px] uppercase text-slate-500 mb-2">
              {searchHits.length} result{searchHits.length === 1 ? '' : 's'}
            </p>
            {searchHits.map((h) => (
              <button
                key={h.slug}
                onClick={() => navigate(h.slug)}
                className="w-full text-left p-2 rounded hover:bg-slate-800/60"
              >
                <div className="text-xs font-medium text-white">{h.title}</div>
                <div className="text-[10px] text-slate-500 mt-0.5">{h.section}</div>
                {h.snippet && (
                  <div className="text-[10px] text-slate-400 mt-1 line-clamp-2">{h.snippet}</div>
                )}
              </button>
            ))}
          </div>
        ) : manifest ? (
          <nav className="p-3 space-y-4">
            {manifest.sections.map((sec) => (
              <div key={sec.id}>
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 px-2">
                  {sec.title}
                </p>
                <ul className="space-y-0.5">
                  {sec.docs.map((d) => {
                    const active = slug === d.slug;
                    return (
                      <li key={d.slug}>
                        <button
                          onClick={() => navigate(d.slug)}
                          className={`w-full text-left px-2 py-1 rounded text-xs flex items-center gap-1 ${
                            active
                              ? 'bg-cyan-500/15 text-cyan-200 border-l-2 border-cyan-400'
                              : 'text-slate-300 hover:bg-slate-800/60 hover:text-white'
                          }`}
                        >
                          {active && <ChevronRight className="w-3 h-3 shrink-0" />}
                          <span className={active ? '' : 'ml-3'}>{d.title}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        ) : (
          <p className="p-4 text-xs text-slate-500">Loading…</p>
        )}
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 px-4 md:px-12 py-6">
        <article className="max-w-3xl mx-auto prose-doc">
          {loading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <DocBody markdown={content} />
          )}
        </article>
      </main>

      <style jsx global>{`
        .prose-doc {
          color: rgb(203 213 225);
          font-size: 14px;
          line-height: 1.7;
        }
        .prose-doc h1 {
          color: white;
          font-size: 1.875rem;
          font-weight: 700;
          margin-top: 0;
          margin-bottom: 1rem;
          padding-bottom: 0.5rem;
          border-bottom: 1px solid rgb(30 41 59);
        }
        .prose-doc h2 {
          color: white;
          font-size: 1.375rem;
          font-weight: 700;
          margin-top: 2rem;
          margin-bottom: 0.75rem;
        }
        .prose-doc h3 {
          color: rgb(226 232 240);
          font-size: 1.125rem;
          font-weight: 600;
          margin-top: 1.5rem;
          margin-bottom: 0.5rem;
        }
        .prose-doc h4 {
          color: rgb(226 232 240);
          font-size: 1rem;
          font-weight: 600;
          margin-top: 1rem;
          margin-bottom: 0.25rem;
        }
        .prose-doc p { margin: 0.75rem 0; }
        .prose-doc ul, .prose-doc ol { margin: 0.75rem 0; padding-left: 1.5rem; }
        .prose-doc li { margin: 0.25rem 0; }
        .prose-doc code {
          background: rgb(15 23 42);
          color: rgb(165 243 252);
          padding: 1px 6px;
          border-radius: 4px;
          font-size: 0.85em;
          border: 1px solid rgb(30 41 59);
        }
        .prose-doc pre {
          background: rgb(2 6 23);
          border: 1px solid rgb(30 41 59);
          border-radius: 8px;
          padding: 1rem;
          overflow-x: auto;
          margin: 1rem 0;
        }
        .prose-doc pre code {
          background: transparent;
          border: 0;
          padding: 0;
          color: rgb(226 232 240);
        }
        .prose-doc blockquote {
          border-left: 3px solid rgb(34 211 238);
          padding: 0.25rem 1rem;
          margin: 1rem 0;
          background: rgba(34, 211, 238, 0.04);
          color: rgb(186 230 253);
        }
        .prose-doc a {
          color: rgb(103 232 249);
          text-decoration: underline;
          text-decoration-color: rgba(103, 232, 249, 0.4);
          text-underline-offset: 3px;
        }
        .prose-doc a:hover { color: rgb(165 243 252); }
        .prose-doc table {
          border-collapse: collapse;
          margin: 1rem 0;
          width: 100%;
          font-size: 0.875em;
        }
        .prose-doc th, .prose-doc td {
          border: 1px solid rgb(30 41 59);
          padding: 0.5rem 0.75rem;
          text-align: left;
        }
        .prose-doc th { background: rgb(15 23 42); color: white; font-weight: 600; }
        .prose-doc tr:nth-child(even) td { background: rgba(15, 23, 42, 0.5); }
        .prose-doc hr {
          border: none;
          border-top: 1px solid rgb(30 41 59);
          margin: 2rem 0;
        }
        .prose-doc strong { color: white; font-weight: 600; }
        .mermaid-block {
          background: rgb(2 6 23);
          border: 1px solid rgb(30 41 59);
          border-radius: 8px;
          padding: 1rem;
          margin: 1rem 0;
          overflow-x: auto;
        }
      `}</style>
    </div>
  );
}

function DocBody({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        code({ node, inline, className, children, ...props }: any) {
          const m = /language-(\w+)/.exec(className || '');
          if (!inline && m && m[1] === 'mermaid') {
            return <MermaidBlock chart={String(children).trim()} />;
          }
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
        a({ href, children }: any) {
          // Rewrite relative .md links to in-app navigation
          if (typeof href === 'string' && href.endsWith('.md')) {
            const cleaned = href.replace(/^\.\.?\//, '').replace(/\.md$/, '').replace(/^\//, '');
            return <a href={`?slug=${encodeURIComponent(cleaned)}`}>{children}</a>;
          }
          return (
            <a href={href} target={href?.startsWith('http') ? '_blank' : undefined} rel="noreferrer">
              {children}
            </a>
          );
        },
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}

function MermaidBlock({ chart }: { chart: string }) {
  const [svg, setSvg] = useState<string>('');
  const [id] = useState(() => `mermaid-${Math.random().toString(36).slice(2, 9)}`);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const mermaid = (await import('mermaid')).default;
      mermaid.initialize({
        startOnLoad: false,
        theme: 'dark',
        themeVariables: {
          background: '#020617',
          primaryColor: '#0f172a',
          primaryTextColor: '#e2e8f0',
          primaryBorderColor: '#475569',
          lineColor: '#64748b',
          secondaryColor: '#0e7490',
          tertiaryColor: '#155e75',
        },
        flowchart: { useMaxWidth: true, htmlLabels: true, curve: 'basis' },
        sequence: { useMaxWidth: true, mirrorActors: false },
        er: { useMaxWidth: true },
      });
      try {
        const { svg } = await mermaid.render(id, chart);
        if (!cancelled) setSvg(svg);
      } catch (e: any) {
        if (!cancelled) setSvg(`<pre style="color:#fca5a5">Mermaid error: ${e.message}</pre>`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  return <div className="mermaid-block" dangerouslySetInnerHTML={{ __html: svg || '<p style="color:#64748b">Rendering diagram…</p>' }} />;
}
