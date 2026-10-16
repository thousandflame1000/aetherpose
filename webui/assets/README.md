# Scene assets

## RobotExpressive

- Creator: Tomas Laulhe / Quaternius.
- License: CC0 1.0, as documented in the bundled upstream `robot/README.md`.
- Downloaded from the Three.js r128 example distribution:
  https://raw.githubusercontent.com/mrdoob/three.js/r128/examples/models/gltf/RobotExpressive/RobotExpressive.glb
- Upstream modifications by Don McCurdy are described in the preserved README.
- The original GLB is bundled locally. Runtime needs no third-party asset host.
- Display height is normalized to 1.65 meters; Idle animation runs in the existing shared render loop. Combat hit volumes remain independent of decorative model geometry.

## Lantern (`lantern/`)

- Khronos glTF Sample Assets, original model by Microsoft (2017); CC0 1.0.
- Source, licence text and upstream provenance: `lantern/README.md` and `lantern/SOURCE.md`.

GLTFLoader is bundled under Three.js's MIT license in `vendor/three`.

## Training props (`props/`)

- Created for this project by `tools/make_scene_props.py` from simple primitives; CC0 1.0.
- Ten self-contained GLB 2.0 files: training cone, plyo box, dumbbell, kettlebell, standing bag, hurdle, gym ball, bench, potted plant, balance pad.
- Real-world size in metres, resting on y = 0. `asset.extras.aetherposeRealScale` tells the page to keep that size instead of fitting the model to 1.2 m.
- Rebuild with `python tools/make_scene_props.py`.

## Training hall

The hall around the arena (`environment.js`) is generated at runtime from primitives and canvas textures; it uses no asset files.
