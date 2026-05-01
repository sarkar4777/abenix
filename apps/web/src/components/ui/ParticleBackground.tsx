'use client';

import { useEffect, useRef } from 'react';

const CODE_FRAGMENTS = [
  'const agent =',
  'async function',
  'import { MCP }',
  'await deploy()',
  'export default',
  'yield stream',
  'tools.connect()',
  'return response',
  'new AgentBuilder',
  'pipeline.run()',
];

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  opacity: number;
}

interface CodeFragment {
  x: number;
  y: number;
  vy: number;
  text: string;
  opacity: number;
  fontSize: number;
}

export default function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationId: number;
    let particles: Particle[] = [];
    let codeFragments: CodeFragment[] = [];

    function resize() {
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }

    resize();
    window.addEventListener('resize', resize);

    const particleCount = Math.floor((canvas.width * canvas.height) / 15000);
    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        size: Math.random() * 2 + 0.5,
        opacity: Math.random() * 0.5 + 0.1,
      });
    }

    for (let i = 0; i < 8; i++) {
      codeFragments.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vy: -(Math.random() * 0.3 + 0.1),
        text: CODE_FRAGMENTS[Math.floor(Math.random() * CODE_FRAGMENTS.length)],
        opacity: 0.04,
        fontSize: Math.random() * 4 + 11,
      });
    }

    function draw() {
      if (!canvas || !ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const gradient = ctx.createRadialGradient(
        canvas.width / 2,
        canvas.height / 2,
        0,
        canvas.width / 2,
        canvas.height / 2,
        canvas.width * 0.7
      );
      gradient.addColorStop(0, 'rgba(6, 182, 212, 0.03)');
      gradient.addColorStop(0.5, 'rgba(168, 85, 247, 0.01)');
      gradient.addColorStop(1, 'transparent');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;

        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(148, 163, 184, ${p.opacity})`;
        ctx.fill();
      }

      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.strokeStyle = `rgba(148, 163, 184, ${0.06 * (1 - dist / 120)})`;
            ctx.stroke();
          }
        }
      }

      for (const f of codeFragments) {
        f.y += f.vy;
        if (f.y < -50) {
          f.y = canvas.height + 50;
          f.x = Math.random() * canvas.width;
          f.text = CODE_FRAGMENTS[Math.floor(Math.random() * CODE_FRAGMENTS.length)];
        }
        ctx.font = `${f.fontSize}px 'SF Mono', 'Fira Code', monospace`;
        ctx.fillStyle = `rgba(148, 163, 184, ${f.opacity})`;
        ctx.fillText(f.text, f.x, f.y);
      }

      animationId = requestAnimationFrame(draw);
    }

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 z-0 pointer-events-none"
      aria-hidden="true"
    />
  );
}
