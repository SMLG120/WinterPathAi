import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { createCityModel, pedestrianParts, SNOW_COUNT, type Part } from './cityModel';

function InstancedPart({ part }: { part: Part }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(() => part.geometry(), [part]);
  const material = useMemo(() => {
    const hasInstanceColor = part.instances.some((i) => i.c);
    const m = new THREE.MeshStandardMaterial({
      color: hasInstanceColor ? '#ffffff' : part.color,
      roughness: part.material === 'snow' ? 0.95 : 0.8,
      metalness: 0,
      flatShading: true,
    });
    if (part.material === 'emissive') {
      m.emissive = new THREE.Color(part.emissive ?? part.color);
      m.emissiveIntensity = part.id === 'path' ? 1.4 : 0.9;
    }
    return m;
  }, [part]);

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const o = new THREE.Object3D();
    const c = new THREE.Color();
    part.instances.forEach((inst, i) => {
      o.position.set(...inst.p);
      o.scale.set(...inst.s);
      o.rotation.set(0, inst.r ?? 0, 0);
      o.updateMatrix();
      mesh.setMatrixAt(i, o.matrix);
      if (inst.c) mesh.setColorAt(i, c.set(inst.c));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [part]);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material],
  );

  return <instancedMesh ref={ref} args={[geometry, material, part.instances.length]} castShadow={false} receiveShadow={false} />;
}

function Snowfall() {
  const ref = useRef<THREE.Points>(null);
  const { positions, speeds } = useMemo(() => {
    const positions = new Float32Array(SNOW_COUNT * 3);
    const speeds = new Float32Array(SNOW_COUNT);
    for (let i = 0; i < SNOW_COUNT; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 40;
      positions[i * 3 + 1] = Math.random() * 18;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 44;
      speeds[i] = 0.6 + Math.random() * 0.9;
    }
    return { positions, speeds };
  }, []);
  useFrame((_, dt) => {
    const pts = ref.current;
    if (!pts) return;
    const attr = pts.geometry.getAttribute('position') as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const step = Math.min(dt, 0.05);
    for (let i = 0; i < SNOW_COUNT; i++) {
      arr[i * 3 + 1]! -= speeds[i]! * step;
      arr[i * 3]! += Math.sin((arr[i * 3 + 1]! + i) * 0.5) * 0.004;
      if (arr[i * 3 + 1]! < 0) arr[i * 3 + 1] = 18;
    }
    attr.needsUpdate = true;
  });
  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#f7fafc" size={0.09} sizeAttenuation transparent opacity={0.9} depthWrite={false} />
    </points>
  );
}

function Pedestrian() {
  const group = useRef<THREE.Group>(null);
  const parts = useMemo(() => pedestrianParts(), []);
  useFrame(({ clock }) => {
    const g = group.current;
    if (!g) return;
    // Walk the highlighted path along the sidewalk, looping.
    const t = (clock.getElapsedTime() * 0.9) % 28;
    g.position.set(4.9, 0.24 + Math.abs(Math.sin(t * 6)) * 0.04, 12 - t);
  });
  useEffect(() => () => parts.forEach((p) => p.geometry.dispose()), [parts]);
  return (
    <group ref={group}>
      {parts.map((p) => (
        <mesh key={p.id} geometry={p.geometry} position={[0, p.y, 0]}>
          <meshStandardMaterial color={p.color} flatShading roughness={0.7} />
        </mesh>
      ))}
    </group>
  );
}

/** Controlled camera: gentle pointer parallax only (no free orbit). */
function CameraRig() {
  const { camera, pointer } = useThree();
  const base = useMemo(() => new THREE.Vector3(-13, 11, 20), []);
  useFrame(() => {
    camera.position.x += (base.x + pointer.x * 2 - camera.position.x) * 0.04;
    camera.position.y += (base.y + pointer.y * 1 - camera.position.y) * 0.04;
    camera.lookAt(0, 1.5, -3);
  });
  return null;
}

export default function Scene3D({ onReady }: { onReady?: () => void }) {
  const parts = useMemo(() => createCityModel(), []);
  const container = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(true);
  const mobile = typeof window !== 'undefined' && window.matchMedia?.('(max-width: 768px)').matches;

  // Idle when off-screen or tab hidden: switch to on-demand rendering.
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    let visible = true;
    const update = () => setActive(visible && document.visibilityState === 'visible');
    const io = new IntersectionObserver(([e]) => {
      visible = !!e?.isIntersecting;
      update();
    });
    io.observe(el);
    document.addEventListener('visibilitychange', update);
    return () => {
      io.disconnect();
      document.removeEventListener('visibilitychange', update);
    };
  }, []);

  return (
    <div ref={container} className="absolute inset-0">
      <Canvas
        frameloop={active ? 'always' : 'demand'}
        dpr={mobile ? 1 : [1, 1.5]}
        camera={{ position: [-13, 11, 20], fov: 40, near: 0.5, far: 120 }}
        gl={{ antialias: !mobile, powerPreference: 'low-power', alpha: true }}
        onCreated={() => onReady?.()}
      >
        <fog attach="fog" args={['#101b2c', 28, 70]} />
        <hemisphereLight args={['#bde8f4', '#101b2c', 0.9]} />
        <directionalLight position={[-10, 18, 8]} intensity={0.9} color="#dfefff" />
        {parts.map((p) => (
          <InstancedPart key={p.id} part={p} />
        ))}
        <Pedestrian />
        <Snowfall />
        <CameraRig />
      </Canvas>
    </div>
  );
}
