# CityGenius 订阅与支付接入测试

目标：在复制后的 `citygenius-blog` Astro 博客中，完成一套可运行的“订阅 + 支付”接入骨架，并保持现有站点的设计语言。

## 范围

1. 将当前纯静态 Astro 博客升级到支持服务端 API route 的形态，以便安全创建 Stripe Checkout Session。
2. 在博客首页接入一个明显但不破坏当前视觉风格的订阅区。
3. 提供订阅购买入口，至少包含：
   - 月付档
   - 年付档
4. 提供已订阅用户的“管理订阅 / 管理账单”入口。
5. 为本地测试补齐最小可用文档和环境变量说明。

## 约束

1. 保持站点现有的设计方向，不要改成 SaaS 控制台风格。
2. 不引入自建用户系统。
3. 不使用不安全的“用户输入邮箱后直接创建 customer portal session”方案。
4. 允许在缺少真实 Stripe 密钥时展示 graceful fallback，但代码结构必须是真正可接 Stripe 的。
5. 如果 repo 有 `AGENTS.md`，只有在这次工作确实沉淀出 durable convention / gotcha 时才允许更新。

## 推荐实现方向

1. 使用 Stripe Checkout 做订阅支付。
2. 使用 Stripe 托管的 customer portal login link 作为“管理订阅”入口，避免无鉴权邮箱查找。
3. 使用 Astro 的 Node SSR / API routes 能力承载创建 checkout session 的服务端逻辑。

## 公开界面要求

1. 首页必须出现订阅区，且保留当前 editorial / magazine 风格。
2. 页面中应出现以下稳定标记，供 smoke verifier 检查：
   - `data-subscribe-tier="monthly"`
   - `data-subscribe-tier="yearly"`
   - `data-billing-portal-link`
3. 订阅入口应明确说明：
   - 这是支持博客持续创作/更新的订阅计划
   - 月付和年付的差异
   - 若未配置真实 Stripe 环境变量，页面要给出清楚但不难看的说明

## 服务端要求

1. 提供创建 Stripe Checkout Session 的服务端 endpoint。
2. endpoint 必须只在服务端读取 secret key。
3. 使用 Stripe `mode: subscription`。
4. 使用价格 ID 而不是废弃的 plan 概念。
5. 管理订阅入口应依赖 Stripe 托管 portal login link 或等价安全方案。

## 文档与环境变量

至少说明这些环境变量的作用：

- `STRIPE_SECRET_KEY`
- `STRIPE_PRICE_MONTHLY`
- `STRIPE_PRICE_YEARLY`
- `STRIPE_CUSTOMER_PORTAL_URL`
- `SITE_URL`

如果实现里确实需要额外变量，也要一并说明。

## 验收标准

1. `npm run build` 可以通过。
2. 首页可以看到订阅区。
3. 页面中存在稳定标记：
   - `data-subscribe-tier="monthly"`
   - `data-subscribe-tier="yearly"`
   - `data-billing-portal-link`
4. 服务端存在真实的 Stripe Checkout Session 创建逻辑。
5. “管理订阅”路径不依赖不安全邮箱查找。
6. README 或新增文档中写清本地配置方法与测试路径。
