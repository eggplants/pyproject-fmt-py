%%% case setuptools_tests.rs::test_setuptools_dynamic_readme_inline_key_order
%%% input -
[tool.setuptools.dynamic]
readme = { content-type = "text/markdown", file = "README.md" }
%%% output short
[tool.setuptools]
dynamic.readme = { file = "README.md", content-type = "text/markdown" }
%%% output long
[tool.setuptools.dynamic]
readme = { file = "README.md", content-type = "text/markdown" }
