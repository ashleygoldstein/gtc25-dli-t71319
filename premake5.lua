-- Shared build scripts from repo_build package.
repo_build = require("omni/repo/build")

-- Repo root
root = repo_build.get_abs_path(".")

-- Run repo_kit_tools premake5-kit that includes a bunch of Kit-friendly tooling configuration.
kit = require("_repo/deps/repo_kit_tools/kit-template/premake5-kit")
kit.setup_all()


-- Registries config for testing
repo_build.prebuild_copy {
    { "%{root}/tools/deps/user.toml", "%{root}/_build/deps/user.toml" },
}

-- Apps: for each app generate batch files and a project based on kit files (e.g. my_name.my_app.kit)
define_app("precise_genai.lab_app.kit")
define_app("precise_genai.lab_app_streaming.kit")
define_app("omni.app.conditioning_for_precise_visual_generative_ai.kit")
define_app("ash_app.test_scene.kit")
define_app("ash_app.test_scene_streaming.kit")