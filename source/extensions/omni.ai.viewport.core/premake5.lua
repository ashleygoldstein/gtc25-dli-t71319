-- Use folder name to build extension name and tag. Version is specified explicitly.
local ext = get_current_extension_info()

-- That will also link whole current "target" folder into as extension target folder:
project_ext (ext)
    repo_build.prebuild_link {
        { "data", ext.target_dir.."/data" },
        { "docs", ext.target_dir.."/docs" },
        { "omni", ext.target_dir.."/omni" },
        { "workflows", ext.target_dir.."/workflows" },
        { "%{root}/_build/target-deps/pip_prebundle", ext.target_dir.."/pip_prebundle" },
    }
