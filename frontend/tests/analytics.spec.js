import { test, expect } from '@playwright/test';

test('refund analysis renders actual charts, evidence and a downloadable report', async ({ page }) => {
  const errors=[]; page.on('pageerror', error=>errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('#db-status')).toHaveText('● 数据库已连接');
  await page.locator('#cases .case').first().click();
  await expect(page.locator('#result')).toBeVisible();
  await expect(page.locator('#kpis')).toContainText('1');
  await expect(page.locator('#anomalies')).toContainText('华北事业部');
  await expect(page.locator('.chart svg')).toHaveCount(2);
  await expect(page.locator('#data-panel tbody tr')).toHaveCount(12);
  await page.getByRole('button',{name:'查询 SQL',exact:true}).click();
  await expect(page.locator('#sql-panel')).toContainText('sales.order_metrics');
  await page.getByRole('button',{name:'指标口径',exact:true}).click();
  await expect(page.locator('#definitions-panel')).toContainText('去重订单数');
  const downloadPromise=page.waitForEvent('download');
  await page.locator('#download').click();
  expect((await downloadPromise).suggestedFilename()).toMatch(/^analysis-.*\.md$/);
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.screenshot({path:'../.runtime/desktop-analysis.png',fullPage:true});
  expect(errors).toEqual([]);
});

test('sales trend, refund reasons and mobile layout remain usable', async ({ page }) => {
  await page.goto('/');
  await page.locator('#cases .case').nth(1).click();
  await expect(page.locator('#result')).toBeVisible();
  await expect(page.locator('.chart svg')).toHaveCount(1);
  await expect(page.locator('#insights')).toContainText('变化');
  await page.locator('#cases .case').nth(2).click();
  await expect(page.locator('#run-title')).toContainText('成功退款金额');
  await expect(page.locator('#result')).toBeVisible();
  await expect(page.locator('#data-panel tbody tr')).toHaveCount(3);
  await page.setViewportSize({width:390,height:844});
  await expect(page.locator('#ask')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path:'../.runtime/mobile-analysis.png',fullPage:true});
});

test('missing model is explicit and never falls back to fake AI results', async ({ page, request }) => {
  const health=await (await request.get('/api/health')).json();
  test.skip(health.model_ready,'Live model configured: do not spend model credits in this UI test.');
  await page.goto('/');
  await page.locator('#question').fill('帮我分析退款率');
  await page.locator('#ask').click();
  await expect(page.locator('#notice')).toContainText('AI 问数尚未配置');
});

test('configured model answers through the UI, streams stages and exports evidence', async ({ page, request }) => {
  test.skip(process.env.LIVE_MODEL_TEST !== '1', 'Opt in explicitly: this test calls the configured model API.');
  test.setTimeout(240000);
  const health = await (await request.get('/api/health')).json();
  expect(health.model_ready).toBe(true);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.locator('#question').fill('分析最近三个完整自然月各部门的订单退款率，标记异常部门并展示趋势');
  const submitted = page.waitForResponse(response => response.url().endsWith('/api/queries') && response.request().method() === 'POST');
  await page.locator('#ask').click();
  const job = await (await submitted).json();
  expect(job.mode).toBe('ai');
  await expect(page.locator('#result')).toBeVisible({timeout: 180000});
  const completed = await (await request.get(`/api/queries/${job.id}`)).json();
  expect(completed.status).toBe('complete');
  expect(completed.result.mode).toBe('ai');
  expect(completed.events.some(event => event.node === 'execute_sql')).toBe(true);
  await expect(page.locator('#kpis')).toContainText('14.21%');
  await expect(page.locator('#anomalies')).toContainText('华北事业部');
  await expect(page.locator('.chart svg')).toHaveCount(2);
  await expect(page.locator('#data-panel tbody tr')).toHaveCount(12);
  const report = await request.get(`/api/queries/${job.id}/report`);
  expect(report.ok()).toBe(true);
  expect(await report.text()).toContain('AI 自然语言问数');
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#download').click();
  expect((await downloadPromise).suggestedFilename()).toMatch(/^analysis-.*\.md$/);
  await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
  await page.screenshot({path: '../.runtime/live-analysis.png', fullPage: true});
  expect(errors).toEqual([]);
});
