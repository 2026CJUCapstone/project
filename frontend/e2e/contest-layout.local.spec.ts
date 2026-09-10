import { test, expect } from '@playwright/test';

test('local card list → detail → back; responsive layout', async ({ page }) => {
  await page.setViewportSize({width:1440,height:960});
  await page.goto('/contests');
  const card = page.getByTestId('contest-card').first();
  await expect(card).toBeVisible();
  await expect(card.getByText('대회 보기')).toBeVisible();
  const target = await card.getAttribute('href');
  await page.screenshot({path:'test-results/contest-list-desktop.png',fullPage:true});
  await card.click();
  await expect(page).toHaveURL(new RegExp(`${target}$`));
  await expect(page.getByTestId('contest-detail-page')).toBeVisible();
  await expect(page.locator('.contest-summary')).toBeVisible();
  await expect(page.locator('.contest-info')).not.toHaveAttribute('open');
  await page.screenshot({path:'test-results/contest-detail-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'스코어보드',exact:true}).click();
  await expect(page.getByRole('table')).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'test-results/contest-detail-mobile.png',fullPage:true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  const bounds = await page.locator('.contest-summary').boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(16);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(374);
  await page.getByRole('link',{name:'콘테스트 목록',exact:true}).click();
  await expect(page).toHaveURL(/\/contests$/);
  await expect(card).toBeVisible();
  await page.screenshot({path:'test-results/contest-list-mobile.png',fullPage:true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('multiple cards have independent destinations and filters (fixture data only)', async ({ page }) => {
  const base = {description:'',startsAt:'2030-01-01T00:00:00Z',endsAt:'2030-01-01T02:00:00Z',serverTime:'2030-01-01T01:00:00Z',published:true,joined:false,canManage:false,participantCount:12,problems:[]};
  const fixtures = [
    {...base,id:'first',title:'입문 알고리즘 콘테스트',state:'running'},
    {...base,id:'second',title:'자료구조 연습 라운드',state:'running'},
    {...base,id:'third',title:'주간 프로그래밍 대회',state:'running'},
    {...base,id:'next',title:'다음 주 콘테스트',state:'upcoming'},
  ];
  // The list endpoint adds query parameters for its filters.  Match only the
  // collection URL, including its optional query string, so this fixture does
  // not fall through to a real local API or swallow the detail routes below.
  await page.route(/\/api\/v1\/contests(?:\?.*)?$/, route => route.fulfill({json:fixtures}));
  await page.route('**/api/v1/contests/second', route => route.fulfill({json:fixtures[1]}));
  await page.route('**/api/v1/contests/second/scoreboard', route => route.fulfill({json:{rows:[],problems:[],pendingCount:0,state:'running'}}));
  await page.setViewportSize({width:1440,height:960});
  await page.goto('/contests');
  await expect(page.getByTestId('contest-card')).toHaveCount(4);
  const boxes = await page.getByTestId('contest-card').evaluateAll(elements => elements.slice(0,3).map(e=>e.getBoundingClientRect().y));
  expect(new Set(boxes).size).toBe(1);
  await page.screenshot({path:'test-results/contest-list-multiple-fixture.png',fullPage:true});
  await page.getByRole('button',{name:/^예정/}).click();
  await expect(page.getByTestId('contest-card')).toHaveCount(1);
  await page.getByRole('button',{name:/^전체/}).click();
  await page.getByRole('searchbox',{name:'대회 검색'}).fill('자료구조');
  await expect(page.getByTestId('contest-card')).toHaveCount(1);
  await page.getByTestId('contest-card').click();
  await expect(page).toHaveURL(/\/contests\/second$/);
  await expect(page.getByRole('heading',{name:'자료구조 연습 라운드'})).toBeVisible();
  await page.setViewportSize({width:820,height:900});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
