# 发布到 GitHub

项目主页位于 `docs/`，所有图片和下载文件均随仓库提供，不需要构建网站或购买服务器。

## 发布范围

- 首个公开版本为经过验证的 TG Harbor 1.0.0。
- 源码取自已交付的 1.0 源码包；Windows 下载包通过原始 SHA-256 校验。
- 发布目录只包含源码、公开文档、演示素材、网站和下载包。
- 不包含本地数据目录、账号会话、API 凭据、WebView 缓存、虚拟环境或日志。

## 一次性授权

在项目目录运行 `gh auth login --hostname github.com --git-protocol https --web --skip-ssh-key`。使用 GitHub 官方设备授权页面，由账号所有者完成登录与权限授权；不要把登录密码或访问令牌写入仓库。

本次准备的官方便携 CLI 位于项目旁边的 `tg-harbor-publish-tools/cli/bin/gh.exe`，配置使用独立的 `tg-harbor-publish-tools/gh-config/`。这两个目录不会上传。

## 发布

授权完成后执行 `发布到GitHub.ps1`：脚本在当前登录账号下创建 **public** 的 `tg-harbor` 仓库，上传源文件，将 GitHub Pages 指向 `main` 分支的 `/docs`，并在仓库简介中设置主页链接。

如果同名仓库已存在，创建操作会停止，不会覆盖它。可以通过 `-RepositoryName` 指定其他名称。首次创建后，脚本保存仓库 ID，重新运行时验证仓库身份后继续。

在仓库的 **Settings → Pages** 和 **Actions** 中确认网站构建成功。公开地址以 GitHub 返回的 `html_url` 为准，确认网页可访问后，可以把主页或仓库地址填入 Telegram API 应用申请表。

参考：[GitHub Pages 发布来源](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)、[GitHub CLI 登录](https://cli.github.com/manual/gh_auth_login)。
