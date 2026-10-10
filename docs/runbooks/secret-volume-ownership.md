# 凭据卷权限恢复（Secret Volume Ownership）

## 问题

设置页保存模型/数据源凭据返回 **503**，且错误提示为「secret store directory is not writable」或类似文案。

原因通常是：Docker 命名卷 `/app/.runtime` 由 **root** 创建，而 API 以 **investment-os** 用户运行，无法写入。

这不是密钥格式错误，也不是未配置 `INVESTMENT_OS_SECRET_STORE_KEY`。

## 安全恢复（推荐）

在 Docker 宿主机、对应 Compose 项目目录执行（**不要**把应用改成 root 运行，也**不要** `chmod 777`）：

```bash
docker exec -u root <api容器名> chown -R investment-os:investment-os /app/.runtime
```

示例（P5 浏览器测试栈）：

```bash
docker exec -u root investment-os-p5-browser-test-investment-api-1 \
  chown -R investment-os:investment-os /app/.runtime
```

标准 Compose 栈：

```bash
docker exec -u root personal-ai-investment-os-investment-api-1 \
  chown -R investment-os:investment-os /app/.runtime
```

然后验证：

```bash
docker exec <api容器名> touch /app/.runtime/writable-probe
docker exec <api容器名> ls -la /app/.runtime
docker exec <api容器名> rm /app/.runtime/writable-probe
```

目录属主应显示 `investment-os investment-os`。

## 新卷

镜像已在构建时创建 `/app/.runtime` 并属主为 `investment-os`。**新建**命名卷时 Docker 通常会继承镜像内目录属主；若仍遇到只读，按上文执行一次 `chown` 即可。

## 不要做的事

- 不要用 root 长期运行 API/Worker
- 不要 `chmod -R 777 /app/.runtime`
- 不要把主密钥或凭据文件提交进仓库

## 相关

- `Dockerfile`：预建 `/app/.runtime` 并 chown
- `src/investment_os/infrastructure/secrets.py`：权限失败时返回明确错误
- ADR-0013 / ADR-0017
