/**
 * ANTI-MATRIX Hero Living Animation Engine
 * Real-Time Canvas 2D Perspective Matrix Grid & Luminous 4-Facet Crystal
 * Concept: Emergence of Innovation out of Rigid Conventional Systems
 */

(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', initMatrixCrystalCanvas);

  function initMatrixCrystalCanvas() {
    const canvas = document.getElementById('heroCrystalMatrixCanvas');
    const heroSection = document.getElementById('heroEnterpriseSection');

    if (!canvas || !heroSection) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let dpr = 1;
    let animationFrameId = null;

    // Mouse tracking with lerp smoothing
    let mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };

    // Anti-Matrix Brand Crystal Colors (from official identity)
    const CRYSTAL_COLORS = {
      topLeft: '#82cc5a',     // Medium vibrant emerald
      bottomLeft: '#619427',  // Deep rich emerald
      topRight: '#a6fd3a',    // Bright electric lime highlight
      bottomRight: '#88e44a', // Vivid spring green
      glow: 'rgba(166, 253, 58, 0.35)',
      deepGlow: 'rgba(16, 185, 129, 0.18)'
    };

    // Particles emerging from grid into crystal
    const PARTICLE_COUNT = 65;
    const particles = [];

    class DivergenceParticle {
      constructor() {
        this.reset(true);
      }

      reset(initial = false) {
        // Position across the perspective matrix field
        this.gridX = (Math.random() - 0.5) * 1200;
        this.gridZ = initial ? Math.random() * 800 + 100 : 800 + Math.random() * 200;
        this.yOffset = initial ? (Math.random() - 0.5) * 200 : 0;
        this.speedZ = 1.2 + Math.random() * 2.2;
        this.liftSpeed = 0.4 + Math.random() * 1.2;
        this.size = 1.5 + Math.random() * 2.5;
        this.opacity = 0;
        this.maxOpacity = 0.4 + Math.random() * 0.5;
        this.color = Math.random() > 0.4 ? '#a6fd3a' : '#82cc5a';
        this.curl = (Math.random() - 0.5) * 0.02;
        this.curlAngle = Math.random() * Math.PI * 2;
      }

      update() {
        this.gridZ -= this.speedZ;
        this.yOffset -= this.liftSpeed; // Elevate upward out of the grid plane
        this.curlAngle += this.curl;
        this.gridX += Math.sin(this.curlAngle) * 0.5;

        // Fade in when entering, fade out when close to camera or lifted high
        if (this.gridZ > 600) {
          this.opacity = Math.min(this.maxOpacity, this.opacity + 0.03);
        } else if (this.gridZ < 150 || this.yOffset < -350) {
          this.opacity -= 0.025;
        } else {
          this.opacity = Math.min(this.maxOpacity, this.opacity + 0.015);
        }

        if (this.gridZ <= 50 || this.opacity <= 0 || this.yOffset < -400) {
          this.reset();
        }
      }

      draw(centerX, horizonY, fov) {
        if (this.gridZ <= 10 || this.opacity <= 0) return;

        const scale = fov / (fov + this.gridZ);
        const px = centerX + this.gridX * scale;
        const py = horizonY + (180 + this.yOffset) * scale;
        const pSize = Math.max(0.8, this.size * scale);

        ctx.save();
        ctx.globalAlpha = Math.max(0, Math.min(1, this.opacity));
        ctx.fillStyle = this.color;
        ctx.shadowColor = this.color;
        ctx.shadowBlur = pSize * 4;
        ctx.beginPath();
        ctx.arc(px, py, pSize, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }

    // Initialize particle pool
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      particles.push(new DivergenceParticle());
    }

    // Resize handler
    function resize() {
      const rect = heroSection.getBoundingClientRect();
      width = rect.width || window.innerWidth;
      height = rect.height || window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);

      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      ctx.scale(dpr, dpr);
    }

    // Mouse move parallax
    function onMouseMove(e) {
      const rect = heroSection.getBoundingClientRect();
      const clientX = e.clientX - rect.left;
      const clientY = e.clientY - rect.top;
      mouse.targetX = (clientX / width - 0.5) * 2; // -1 to 1
      mouse.targetY = (clientY / height - 0.5) * 2; // -1 to 1
    }

    function onMouseLeave() {
      mouse.targetX = 0;
      mouse.targetY = 0;
    }

    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', onMouseMove, { passive: true });
    document.addEventListener('mouseleave', onMouseLeave);
    resize();

    // ── DRAWING FUNCTIONS ──

    // 1. Perspective Matrix Grid (The System)
    function drawPerspectiveMatrix(time, centerX, horizonY, fov) {
      ctx.save();

      const gridSpacing = 40;
      const maxZ = 900;
      const minZ = 40;
      const gridWidth = 1400;
      const gridYBase = 180; // Distance below horizon

      // Offset grid lines over time for continuous subtle forward motion
      const zOffset = (time * 35) % gridSpacing;

      ctx.lineWidth = 1;

      // Draw Transverse Grid Lines (Horizontal in perspective)
      for (let z = minZ + zOffset; z < maxZ; z += gridSpacing) {
        const scale = fov / (fov + z);
        const y = horizonY + gridYBase * scale;
        const leftX = centerX - (gridWidth * 0.5) * scale;
        const rightX = centerX + (gridWidth * 0.5) * scale;

        // Fade with distance
        const alpha = Math.pow(1 - z / maxZ, 1.8) * 0.22;
        if (alpha <= 0.005) continue;

        ctx.strokeStyle = `rgba(130, 204, 90, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(leftX, y);
        ctx.lineTo(rightX, y);
        ctx.stroke();
      }

      // Draw Longitudinal Grid Lines (Radiating toward vanishing point)
      const numLongLines = 28;
      for (let i = -numLongLines / 2; i <= numLongLines / 2; i++) {
        const xOffset = i * (gridWidth / numLongLines);
        const nearScale = fov / (fov + minZ);
        const farScale = fov / (fov + maxZ);

        const xNear = centerX + xOffset * nearScale;
        const yNear = horizonY + gridYBase * nearScale;

        const xFar = centerX + xOffset * farScale;
        const yFar = horizonY + gridYBase * farScale;

        // Center lines slightly brighter
        const centerFactor = 1 - Math.abs(i) / (numLongLines / 2);
        const alpha = Math.max(0.04, centerFactor * 0.18);

        ctx.strokeStyle = `rgba(130, 204, 90, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(xNear, yNear);
        ctx.lineTo(xFar, yFar);
        ctx.stroke();
      }

      // Matrix Grid Pulses (Data energy packet along a grid line)
      for (let p = 0; p < 3; p++) {
        const pulseProg = ((time * 0.4 + p * 0.33) % 1);
        const pulseZ = minZ + pulseProg * (maxZ - minZ);
        const scale = fov / (fov + pulseZ);
        const pulseY = horizonY + gridYBase * scale;
        const pAlpha = Math.sin(pulseProg * Math.PI) * 0.35;

        const pulseGrad = ctx.createLinearGradient(centerX - 350 * scale, pulseY, centerX + 350 * scale, pulseY);
        pulseGrad.addColorStop(0, 'transparent');
        pulseGrad.addColorStop(0.5, `rgba(166, 253, 58, ${pAlpha})`);
        pulseGrad.addColorStop(1, 'transparent');

        ctx.strokeStyle = pulseGrad;
        ctx.lineWidth = 2 * scale;
        ctx.beginPath();
        ctx.moveTo(centerX - 400 * scale, pulseY);
        ctx.lineTo(centerX + 400 * scale, pulseY);
        ctx.stroke();
      }

      ctx.restore();
    }

    // 2. The Iconic 4-Facet Anti-Matrix Crystal
    function drawAntiMatrixCrystal(time, cx, cy) {
      ctx.save();

      // Floating oscillation & gentle pitch/yaw rotation
      const floatY = Math.sin(time * 1.2) * 9;
      const floatX = Math.cos(time * 0.8) * 4;
      const rotZ = Math.sin(time * 0.5) * 0.04 + mouse.x * 0.08;
      const scalePulse = 1 + Math.sin(time * 1.5) * 0.025;

      const crystalCenterX = cx + floatX + mouse.x * 18;
      const crystalCenterY = cy + floatY + mouse.y * 12;

      ctx.translate(crystalCenterX, crystalCenterY);
      ctx.rotate(rotZ);
      ctx.scale(scalePulse, scalePulse);

      // Deep Ambient Radiance / Volumetric Backglow
      const glowRadius = 140;
      const ambientGlow = ctx.createRadialGradient(0, 0, 10, 0, 0, glowRadius);
      ambientGlow.addColorStop(0, 'rgba(166, 253, 58, 0.28)');
      ambientGlow.addColorStop(0.4, 'rgba(130, 204, 90, 0.14)');
      ambientGlow.addColorStop(0.8, 'rgba(16, 185, 129, 0.04)');
      ambientGlow.addColorStop(1, 'transparent');

      ctx.fillStyle = ambientGlow;
      ctx.beginPath();
      ctx.arc(0, 0, glowRadius, 0, Math.PI * 2);
      ctx.fill();

      // Crystal Dimensions (Anti-Matrix logo diamond proportion)
      const baseWidth = 52;
      const baseHeight = 64;
      const gap = 2.4; // Seam between the 4 crystalline facets
      const specularShift = Math.sin(time * 2.0) * 0.3;

      // Helper function to draw a multifaceted facet
      function renderFacet(p1, p2, p3, baseColor, highlightColor, shadowColor) {
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(p1[0], p1[1]);
        ctx.lineTo(p2[0], p2[1]);
        ctx.lineTo(p3[0], p3[1]);
        ctx.closePath();

        // Facet gradient for jewel-like refraction
        const grad = ctx.createLinearGradient(p1[0], p1[1], p3[0], p3[1]);
        grad.addColorStop(0, highlightColor);
        grad.addColorStop(0.55, baseColor);
        grad.addColorStop(1, shadowColor);

        ctx.fillStyle = grad;
        ctx.shadowColor = 'rgba(166, 253, 58, 0.45)';
        ctx.shadowBlur = 12;
        ctx.fill();

        // Facet Beveled Crisp Edge Highlight
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.55)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
      }

      // Facet 1: Top-Left (Vibrant Emerald)
      renderFacet(
        [-gap, -baseHeight],
        [-baseWidth, -gap],
        [-gap, -gap],
        CRYSTAL_COLORS.topLeft,
        '#bbf870',
        '#5d9630'
      );

      // Facet 2: Bottom-Left (Deep Rich Emerald)
      renderFacet(
        [-gap, -gap],
        [-baseWidth, gap],
        [-gap, baseHeight],
        CRYSTAL_COLORS.bottomLeft,
        '#7bb53c',
        '#3a6314'
      );

      // Facet 3: Top-Right (Electric Lime Highlight - Key Spark)
      renderFacet(
        [gap, -baseHeight],
        [gap, -gap],
        [baseWidth, -gap],
        CRYSTAL_COLORS.topRight,
        '#ffffff',
        '#8dd924'
      );

      // Facet 4: Bottom-Right (Vivid Spring Green)
      renderFacet(
        [gap, -gap],
        [gap, baseHeight],
        [baseWidth, gap],
        CRYSTAL_COLORS.bottomRight,
        '#aef46e',
        '#569b22'
      );

      // Refractive Prismatic Sparkle Beam across the crystal
      ctx.save();
      const gleamAngle = time * 0.9;
      const gleamX = Math.cos(gleamAngle) * 35;
      const gleamY = Math.sin(gleamAngle) * 45;

      const sparkleGrad = ctx.createRadialGradient(gleamX, gleamY, 0, gleamX, gleamY, 24);
      sparkleGrad.addColorStop(0, 'rgba(255, 255, 255, 0.9)');
      sparkleGrad.addColorStop(0.3, 'rgba(166, 253, 58, 0.65)');
      sparkleGrad.addColorStop(1, 'transparent');

      ctx.fillStyle = sparkleGrad;
      ctx.beginPath();
      ctx.arc(gleamX, gleamY, 24, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      ctx.restore();
    }

    // ── MAIN ANIMATION LOOP ──
    let startTime = performance.now();

    function renderFrame(now) {
      const time = (now - startTime) * 0.001;

      // Smooth mouse lerp
      mouse.x += (mouse.targetX - mouse.x) * 0.06;
      mouse.y += (mouse.targetY - mouse.y) * 0.06;

      ctx.clearRect(0, 0, width, height);

      // Perspective horizon parameters
      const centerX = width * 0.5;
      const horizonY = height * 0.44;
      const fov = 340;

      // 1. Draw Perspective Matrix Grid Plane
      drawPerspectiveMatrix(time, centerX, horizonY, fov);

      // 2. Update & Draw Divergence Particles
      for (let i = 0; i < particles.length; i++) {
        particles[i].update();
        particles[i].draw(centerX, horizonY, fov);
      }

      // 3. Draw The Luminous Anti-Matrix Crystal
      const crystalY = height * 0.38;
      drawAntiMatrixCrystal(time, centerX, crystalY);

      animationFrameId = requestAnimationFrame(renderFrame);
    }

    // Start loop
    animationFrameId = requestAnimationFrame(renderFrame);

    // Pause when tab is not visible to save CPU/GPU battery
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
      } else {
        startTime = performance.now();
        animationFrameId = requestAnimationFrame(renderFrame);
      }
    });
  }
})();
