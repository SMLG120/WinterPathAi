import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { createExplainerModel, type ExplainerPart, type Lens } from './explainerModel';

function PartMesh({ part, lens }: { part: ExplainerPart; lens: Lens }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(() => part.geometry(), [part]);
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: part.color,
        roughness: part.material === 'snow' ? 0.95 : 0.8,
        metalness: 0,
        flatShading: true,
        transparent: true,
      }),
    [part],
  );
  const selected = part.lens === lens;
  const dimmed = part.lens !== null && !selected;

  useLayoutEffect(() => {
    // Selected lens glows in its own colour; other lens elements fade back.
    material.emissive.set(selected ? part.color : '#000000');
    material.emissiveIntensity = selected ? 0.7 : 0;
    material.opacity = dimmed ? 0.35 : 1;
    material.depthWrite = !dimmed;
    material.needsUpdate = true;
  }, [material, part.color, selected, dimmed]);

  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const o = new THREE.Object3D();
    part.instances.forEach((inst, i) => {
      o.position.set(...inst.p);
      o.scale.set(...inst.s);
      o.rotation.set(0, inst.r ?? 0, 0);
      o.updateMatrix();
      mesh.setMatrixAt(i, o.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }, [part]);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material],
  );

  return <instancedMesh ref={ref} args={[geometry, material, part.instances.length]} />;
}

/** frameloop="demand": nothing animates; one frame is drawn per lens change. */
function Invalidate({ lens }: { lens: Lens }) {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => invalidate(), [lens, invalidate]);
  return null;
}

export default function ExplainerScene({ lens, onReady }: { lens: Lens; onReady?: () => void }) {
  const parts = useMemo(() => createExplainerModel(), []);
  const mobile = typeof window !== 'undefined' && window.matchMedia?.('(max-width: 768px)').matches;
  return (
    <Canvas
      frameloop="demand"
      dpr={mobile ? 1 : [1, 1.5]}
      camera={{ position: [10, 8, 11], fov: 38, near: 0.5, far: 60 }}
      gl={{ antialias: !mobile, powerPreference: 'low-power', alpha: true }}
      onCreated={({ camera }) => {
        camera.lookAt(-0.5, 1.2, 0);
        onReady?.();
      }}
    >
      <ambientLight intensity={0.55} />
      <hemisphereLight args={['#dff3fa', '#33405a', 0.9]} />
      <directionalLight position={[8, 14, 10]} intensity={1.2} color="#f2f7ff" />
      {parts.map((p) => (
        <PartMesh key={p.id} part={p} lens={lens} />
      ))}
      <Invalidate lens={lens} />
    </Canvas>
  );
}
