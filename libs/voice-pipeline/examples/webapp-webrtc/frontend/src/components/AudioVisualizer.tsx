import { useEffect, useRef } from 'react';
import { useAgentStore } from '../hooks/useAgentState';

interface AudioVisualizerProps {
  isActive: boolean;
}

export function AudioVisualizer({ isActive }: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>();
  const { vadLevel, agentState } = useAgentStore();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resizeCanvas = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      if (rect) {
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    // Animation state
    let bars: number[] = new Array(32).fill(0);
    let targetBars: number[] = new Array(32).fill(0);

    const animate = () => {
      if (!ctx || !canvas) return;

      // Clear canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Update target bars based on state
      if (isActive && (agentState === 'listening' || agentState === 'speaking')) {
        const baseLevel = vadLevel || 0.3;
        targetBars = bars.map((_, i) => {
          const noise = Math.random() * 0.3;
          const wave = Math.sin(Date.now() / 200 + i * 0.3) * 0.2;
          return Math.min(1, baseLevel + noise + wave);
        });
      } else {
        targetBars = bars.map(() => 0.05);
      }

      // Smooth animation
      bars = bars.map((bar, i) => {
        const target = targetBars[i];
        const diff = target - bar;
        return bar + diff * 0.15;
      });

      // Draw bars
      const barWidth = canvas.width / bars.length - 2;
      const centerY = canvas.height / 2;

      // Determine color based on state
      let color = '#6b7280'; // gray
      if (agentState === 'listening') {
        color = '#eab308'; // yellow
      } else if (agentState === 'speaking') {
        color = '#22c55e'; // green
      } else if (agentState === 'processing') {
        color = '#3b82f6'; // blue
      }

      bars.forEach((height, i) => {
        const barHeight = height * (canvas.height - 20);
        const x = i * (barWidth + 2) + 1;

        // Create gradient
        const gradient = ctx.createLinearGradient(x, centerY - barHeight / 2, x, centerY + barHeight / 2);
        gradient.addColorStop(0, color);
        gradient.addColorStop(0.5, color + 'cc');
        gradient.addColorStop(1, color);

        ctx.fillStyle = gradient;

        // Draw rounded bar
        const radius = Math.min(barWidth / 2, 3);
        ctx.beginPath();
        ctx.roundRect(
          x,
          centerY - barHeight / 2,
          barWidth,
          Math.max(4, barHeight),
          radius
        );
        ctx.fill();
      });

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener('resize', resizeCanvas);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [isActive, vadLevel, agentState]);

  return (
    <div className="w-full h-full relative">
      <canvas
        ref={canvasRef}
        className="waveform-canvas"
      />
      {!isActive && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-gray-500 text-sm">Conecte para ver a visualizacao</span>
        </div>
      )}
    </div>
  );
}
