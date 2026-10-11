// Automated dashboard regression using a local in-memory API fixture.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.TEST_BROWSER_CHANNEL || undefined, executablePath:process.env.TEST_BROWSER_EXECUTABLE || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const root = path.join(__dirname, '..');
    let signedIn = false;
    const children = [{id:'an',display_name:'An',has_pin:true},{id:'binh',display_name:'Bình',has_pin:true}];
    const policies = new Map(children.map(child => [child.id,{child_id:child.id,version:1,enabled:true,weekday_minutes:90,weekend_minutes:120,schedule:Array(7).fill('1'.repeat(48))}]));
    const rules = new Map(children.map(child => [child.id,{child_id:child.id,version:1,enabled:true,domain_mode:'blocklist',app_mode:'blocklist',domain_allow:['example.org'],domain_block:[child.id+'.example.test'],safety_domains:['111.vn'],app_allow:[],app_block:[]}]));
    const recorded = [];
    let chartRequests = 0;
    let domainQueries = 3;
    let chartSeconds = 80;
    await page.route('http://ogk.test/**', async route => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      if (url.pathname === '/') return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'dashboard/index.html'),'utf8')});
      if (url.pathname.startsWith('/static/')) return route.fulfill({contentType:url.pathname.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(path.join(root,'dashboard',url.pathname.slice(1)),'utf8')});
      const api = url.pathname.slice(4);
      let body, status = 200;
      const input = route.request().postDataJSON();
      if (api === '/auth/me') { status = signedIn ? 200 : 401; body = signedIn ? {email:'parent@example.test',csrf_token:'csrf-test'} : {detail:'Please sign in'}; }
      else if (api === '/auth/login') { signedIn = true; body={email:'parent@example.test',csrf_token:'csrf-test'}; }
      else if (api === '/auth/logout') { signedIn = false; status = 204; }
      else if (api === '/parent/events') return route.fulfill({contentType:'text/event-stream',body:'event: ready\ndata: {}\n\n'});
      else if (api === '/children' && method === 'GET') body=children;
      else if (api === '/children' && method === 'POST') { body={id:'new',display_name:input.display_name,has_pin:true}; children.push(body); policies.set('new',{...policies.get('an'),child_id:'new'}); rules.set('new',{...rules.get('an'),child_id:'new'}); }
      else if (api.endsWith('/policy')) { const id=api.split('/')[2]; if(method==='PUT') policies.set(id,{...input,child_id:id,version:policies.get(id).version+1}); body=policies.get(id); }
      else if (api.endsWith('/filtering')) { const id=api.split('/')[2]; if(method==='PUT') { assert.equal(route.request().headers()['x-csrf-token'],'csrf-test'); assert.equal(input.expected_version,rules.get(id).version); rules.set(id,{...input,child_id:id,version:input.expected_version+1}); recorded.push(input); } body=rules.get(id); }
      else if (api.endsWith('/pin')) body={ok:true};
      else if (api === '/enrollment-codes') body={code:'ABCDEFG2'};
      else if (api === '/devices') body=[{id:'lab',display_name:'Lab PC',online:true,active_user:'An',policy_version:1,last_seen:1,time_status_at:1}];
      else if (api === '/audit') body=[
        {ts:1700000000,action:'filtering_updated',child_id:'an',old_value:{domain_block:['old.test']},new_value:{domain_block:['new.test']}},
        {ts:1699999999,action:'policy_updated',child_id:'an',old_value:{weekday_minutes:90,schedule:Array(7).fill('0'.repeat(48))},new_value:{weekday_minutes:75,schedule:['11'+'0'.repeat(46),...Array(6).fill('0'.repeat(48))]}},
      ];
      else if (api === '/time-requests') body=[];
      else if (api.startsWith('/devices/') && api.endsWith('/commands')) body={realtime_delivered:true};
      else if (api.endsWith('/activity-events')) body={items:[{id:'evt',event:{ts:1700000000,subject:'example.test'},explanation:{reason:'Trang web bị chặn',rule_author:'Phụ huynh'}}],has_more:false};
      else if (api.endsWith('/activity-data/deletion')) body={generation:0,pending_devices:[],complete:true};
      else if (api.endsWith('/activity-report.csv')) return route.fulfill({contentType:'text/csv; charset=utf-8',headers:{'Content-Disposition':'attachment; filename="test-week.csv"'},body:'\ufeffNhóm,Ngày,Giá trị\r\nThời gian dùng máy,2026-10-11,120\r\n'});
      else if (api.endsWith('/activity-report/chart.png')) { chartRequests++; return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'tests/assets',url.searchParams.get('kind')==='apps'?'sample-apps.png':'sample-columns.png'))}); }
      else if (api.endsWith('/activity-report')) { const id=api.split('/')[2]; const days=Number(url.searchParams.get('days')); const daily=days===56?Array.from({length:56},(_,i)=>({date:new Date(Date.UTC(2026,9,11-55+i)).toISOString().slice(0,10),duration_sec:i>=54?(i===54?40:chartSeconds):0})):[{date:'2026-10-10',duration_sec:40},{date:'2026-10-11',duration_sec:chartSeconds}]; body={start_date:'2026-10-05',end_date:'2026-10-11',total_duration_sec:40+chartSeconds,blocked_count:2,daily,weekly:[{week_start:'2026-10-05',duration_sec:40+chartSeconds}],top_apps:[{subject:id+'-paint.exe',duration_sec:days===1?60:days===7?420:900,starts:1}],top_domains:[{subject:id+'.example.test',queries:domainQueries}],requests:[{created_at:1700000000,minutes:15,status:'pending'}]}; }
      else { status=404; body={detail:'Unknown '+api}; }
      await route.fulfill({status,contentType:'application/json',body:status===204?'':JSON.stringify(body)});
    });
    await page.goto('http://ogk.test/');
    await page.locator('#login-form input[name=email]').fill('parent@example.test');
    await page.locator('#login-form input[name=password]').fill('test-password');
    await page.locator('#login-form button').click();
    await page.waitForFunction(() => document.querySelector('#child-select').value === 'an' && document.querySelector('#domain_block-list .domain-name')?.textContent === 'an.example.test');
    assert.deepEqual(await page.getByRole('tab').allTextContents(),['Dashboard','Báo cáo','Chính sách thời gian','Quản lí web & ứng dụng','Sự kiện']);
    await page.waitForFunction(() => document.querySelector('#report-apps').textContent.includes('an-paint.exe'));
    assert.match(await page.locator('#report-apps').innerText(),/7 phút/);
    assert.equal(await page.locator('#report-daily img').count(),1);
    await page.waitForFunction(() => document.querySelector('#report-daily img').naturalWidth === 800 && document.querySelector('#report-apps img').naturalWidth === 440);
    assert.deepEqual(await page.locator('.report-axis').allTextContents(),['7 ngày trướcNgay bây giờ','8 tuần trướcNgay bây giờ']);
    assert.match(await page.locator('#report-daily-total').innerText(),/0 giờ 02 phút/);
    assert.match(await page.locator('#report-weekly-total').innerText(),/0 giờ 02 phút/);
    const initialChartRequests = chartRequests;
    await page.evaluate(() => refreshStatus());
    assert.equal(chartRequests,initialChartRequests);
    domainQueries = 4;
    await page.evaluate(() => refreshStatus());
    assert.match(await page.locator('#report-domains').innerText(),/3 lượt truy vấn/);
    await page.evaluate(() => { reportCache.loadedAt -= REPORT_REFRESH_MS; return refreshReport(); });
    await Promise.all(['#report-daily img','#report-weekly img','#report-apps img'].map(selector => page.locator(selector).evaluate(image => image.decode())));
    assert.match(await page.locator('#report-domains').innerText(),/4 lượt truy vấn/);
    assert.equal(chartRequests,initialChartRequests);
    chartSeconds = 100;
    await page.evaluate(() => { reportCache.loadedAt -= REPORT_REFRESH_MS; return refreshReport(); });
    await Promise.all(['#report-daily img','#report-weekly img'].map(selector => page.locator(selector).evaluate(image => image.decode())));
    assert.equal(chartRequests,initialChartRequests + 2);
    assert.equal(await page.locator('#report-daily .report-column-hit').count(),7);
    assert.equal(await page.locator('#report-weekly .report-column-hit').count(),8);
    assert.match(await page.locator('#report-daily .report-column-hit').last().getAttribute('title'),/2026-10-11/);
    assert.match(await page.locator('#report-weekly .report-column-hit').last().getAttribute('title'),/Tuần .* – 2026-10-11: 2 phút/);
    assert.equal(await page.locator('#overview-panel #report-title').count(),0);
    assert.match(await page.locator('#audit').innerText(),/Thêm web bị chặn: new.test/);
    assert.match(await page.locator('#audit').innerText(),/Xóa web bị chặn: old.test/);
    assert.match(await page.locator('#audit').innerText(),/Ngày thường: 90 phút → 75 phút/);
    assert.match(await page.locator('#audit').innerText(),/Thứ hai: không cho dùng → 00:00–01:00/);
    await page.locator('#report-tab').click();
    await page.locator('#report-app-period').selectOption('1');
    await page.waitForFunction(() => document.querySelector('#report-apps').textContent.includes('1 phút'));
    await page.locator('#report-app-period').selectOption('90');
    await page.waitForFunction(() => document.querySelector('#report-apps').textContent.includes('15 phút'));
    await page.locator('#report-app-period').selectOption('1');
    await page.waitForFunction(() => document.querySelector('#report-apps').textContent.includes('1 phút'));
    assert.equal(await page.locator('#report-blocked').innerText(),'Bị chặn: 2 lần');
    await page.locator('#report-days').selectOption('7');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export-week').click();
    assert.equal((await downloadPromise).suggestedFilename(),'bao-cao-tuan.csv');
    if (process.env.REPORT_SCREENSHOT_PATH) await page.screenshot({path:process.env.REPORT_SCREENSHOT_PATH,fullPage:true});
    for (const id of ['overview','report','time-policy','filtering','activity']) {
      await page.locator('#'+id+'-tab').click();
      assert.equal(await page.locator('#'+id+'-panel').isVisible(),true);
      assert.equal(await page.locator('[role=tab][aria-selected=true]').count(),1);
    }
    await page.locator('#time-policy-tab').click();
    await page.locator('#policy-form input[name=weekday_minutes]').fill('75');
    await page.locator('#policy-form button').filter({hasText:'Lưu chính sách'}).click();
    await page.waitForFunction(() => document.querySelector('#policy-version').textContent.includes('2'));
    assert.equal(policies.get('an').weekday_minutes,75);
    await page.locator('#filtering-tab').click();
    await page.locator('#domain_block-new').fill('https://NEW.example.org/path?q=private');
    await page.locator('[data-add-domain=domain_block]').click();
    assert.equal(await page.locator('#domain_block-list .domain-row').count(),2);
    assert.equal(await page.locator('#domain_block-new').inputValue(),'');
    // A background policy refresh must not destroy unsaved domains.
    await page.evaluate(() => loadPolicy());
    assert.equal(await page.locator('#domain_block-list .domain-row').count(),2);
    const added = page.locator('#domain_block-list .domain-row').filter({hasText:'new.example.org'});
    await added.getByRole('button',{name:'Chỉnh sửa new.example.org',exact:true}).click();
    await page.locator('.domain-row-edit input').fill('edited.example.org');
    await page.locator('.domain-row-edit').getByRole('button',{name:'Lưu dòng',exact:true}).click();
    await page.getByRole('button',{name:'Xóa an.example.test',exact:true}).click();
    await page.locator('#filtering-form button[type=submit]').click();
    await page.waitForFunction(() => document.querySelector('#filtering-draft-status').textContent === '');
    assert.deepEqual(rules.get('an').domain_block,['edited.example.org']);
    assert.deepEqual(rules.get('an').domain_allow,['example.org']);
    assert.deepEqual(rules.get('an').safety_domains,['111.vn']);
    assert.equal(recorded.length,1);
    await page.locator('#domain_allow-new').fill('example.org');
    await page.locator('[data-add-domain=domain_allow]').click();
    assert.equal(await page.locator('#domain_allow-new').evaluate(input => input.validity.customError),true);
    await page.locator('#domain_allow-new').fill('https://learn.example.edu/lesson');
    await page.locator('[data-add-domain=domain_allow]').click();
    await page.locator('#filtering-form button[type=submit]').click();
    await page.waitForFunction(() => document.querySelector('#filtering-draft-status').textContent === '');
    assert.deepEqual(rules.get('an').domain_allow,['example.org','learn.example.edu']);
    await page.locator('#child-select').selectOption('binh');
    await page.waitForFunction(() => document.querySelector('#domain_block-list .domain-name')?.textContent === 'binh.example.test');
    await page.waitForFunction(() => document.querySelector('#report-apps').textContent.includes('binh-paint.exe'));
    assert.equal(await page.locator('#policy-form input[name=weekday_minutes]').inputValue(),'90');
    await page.locator('#activity-tab').click();
    await page.waitForSelector('#activity-rows tr');
    assert.equal(await page.locator('#activity-rows').innerText().then(text=>text.includes('Trang web bị chặn')),true);
    await page.locator('#overview-tab').click();
    await page.getByRole('button',{name:'Khóa ngay',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#message').textContent === 'Agent đã nhận lệnh qua kênh khẩn.');
    await page.locator('#code-form input[name=consent]').check();
    await page.locator('#code-form button').click();
    await page.waitForFunction(() => document.querySelector('#pairing-code').textContent === 'ABCDEFG2');
    await page.locator('#time-policy-tab').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#filtering-tab').getAttribute('aria-selected'),'true');
    if (process.env.TEST_SCREENSHOT_PATH) await page.screenshot({path:process.env.TEST_SCREENSHOT_PATH,fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),true);
    assert.equal(await page.locator('.workspace-tabs').evaluate(tabs => getComputedStyle(tabs).overflowY),'visible');
    assert.equal(await page.locator('.workspace-tabs').evaluate(tabs => tabs.scrollWidth <= tabs.clientWidth),true);
    await page.locator('#logout').click();
    await page.waitForSelector('#login-panel', {state:'visible'});
    assert.equal(await page.locator('#login-panel').isVisible(),true);
    assert.equal(await page.locator('#workspace').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('Parent dashboard checks passed: login, reports/charts/CSV download, five tabs, audit details, policy save, domain add/edit/delete/persistence, draft refresh, profile switching, events, commands, enrollment, keyboard, mobile, logout.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
