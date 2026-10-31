# 发布到 GitHub（RoseSI / Live-interpreter）

本文按「已经有空仓库」的状态写。仓库地址以
`https://github.com/<你的用户名>/Live-interpreter` 为例。

## 0. 上传前检查

```powershell
cd /d E:\JetBrains\PycharmProjects\SI

git status --short
git status --ignored
```

确认没有：

- `dist/`、`release/`、`venv/`、`testdata_ui/`
- `%LOCALAPPDATA%` 里的配置 / SQLite / API Key
- 任何 `sk-...` 字符串

仓库根目录的 `.gitignore` 已经排除了这些路径。

## 1. 推送源码到 GitHub

先确认提交作者是你的 GitHub 信息：

```powershell
git config user.name "你的GitHub用户名"
git config user.email "你的GitHub邮箱"
git commit --amend --reset-author --no-edit
```

添加远程仓库并推送：

```powershell
git remote add origin https://github.com/<你的用户名>/Live-interpreter.git
git branch -M main
git push -u origin main
```

如果远程仓库创建时勾选了 README，先同步再推：

```powershell
git pull --rebase origin main
git push -u origin main
```

**上传位置**：源码通过 `git push` 上传到仓库的 **Code** 页面，不是在 Releases 里。

## 2. 构建 RoseSI 安装包

需要先安装：

- Python 3.10 venv（项目已有）
- Inno Setup 6（默认路径 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`）

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

产物：

- 便携版目录：`dist/RoseSI/`
- 安装包：`release/RoseSI-1.2.0-Setup.exe`

可以先自检：

```powershell
$env:SI_DATA_DIR="$env:TEMP\rosesi-package-check"
.\dist\RoseSI\RoseSI.exe --package-check
```

## 3. 拆分 GitHub 附件

GitHub Release **单个文件最大 2 GiB**，安装包通常 3 GB 以上，必须拆分。
项目自带脚本：

```powershell
.\venv\Scripts\python.exe tools\split_release.py release\RoseSI-1.2.0-Setup.exe
```

输出：

```text
release\RoseSI-1.2.0-Setup.exe.part001
release\RoseSI-1.2.0-Setup.exe.part002
release\SHA256.txt
```

每个 part 默认 1.9 GB，低于 2 GiB 上限。

用户下载全部分卷后合并：

```bat
copy /b RoseSI-1.2.0-Setup.exe.part001 + RoseSI-1.2.0-Setup.exe.part002 RoseSI-1.2.0-Setup.exe
```

然后核对 `SHA256.txt`：

```powershell
Get-FileHash -Algorithm SHA256 .\RoseSI-1.2.0-Setup.exe
```

## 4. 创建 Release 并上传附件

**上传位置：**

1. 打开仓库主页 `https://github.com/<你的用户名>/Live-interpreter`
2. 看右侧栏，点击 **Releases**
3. 点击 **Draft a new release**
4. Tag 选择或输入 `v1.2.0`
5. Release title 填 `RoseSI 1.2.0`
6. 在 **Attach binaries by dropping them here or selecting them** 区域上传：
   - `RoseSI-1.2.0-Setup.exe.part001`
   - `RoseSI-1.2.0-Setup.exe.part002`
   - `SHA256.txt`
   - 可选：`RELEASE_NOTES_v1.2.0.md`
7. 点击 **Publish release**

也可以先打 tag：

```powershell
git tag -a v1.2.0 -m "RoseSI 1.2.0"
git push origin v1.2.0
```

如果安装了 GitHub CLI：

```powershell
gh release create v1.2.0 `
  .\release\RoseSI-1.2.0-Setup.exe.part001 `
  .\release\RoseSI-1.2.0-Setup.exe.part002 `
  .\release\SHA256.txt `
  --title "RoseSI 1.2.0" `
  --notes-file .\RELEASE_NOTES_v1.2.0.md
```

> 网页上传大文件可能超时；优先用 `gh release upload`。

## 5. 发布后检查

- Release 页面能下载所有 part，数量正确
- `SHA256.txt` 与文件一致
- 下载分卷、合并、安装、启动一次
- `RoseSI.exe --package-check` 输出 `api_key_empty_by_default: true`

## 6. 常见问题

### 安装包需要拆分吗？

需要。只要单个文件超过 2 GiB，GitHub 就会拒绝。

### 便携版太大怎么办？

可以对 `dist/RoseSI` 打包后再拆分；也可以只发布安装版，便携版由用户自行从源码构建。

### 可以把模型放进 Git 仓库吗？

不建议。模型权重受各自许可证约束且体积大。仓库只放 `packaging/models.json` 和下载脚本；安装包内置模型时在 Release 中分发，并保留 `LICENSES/`、`THIRD_PARTY_NOTICES.md`。

### API Key 会泄露吗？

仓库和安装包都不包含 Key。用户 Key 只保存在本机 `%LOCALAPPDATA%\LocalInterpreter`，由 Windows DPAPI 加密。
