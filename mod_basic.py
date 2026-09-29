from .setup import *
from .model import ModelItem
import requests
import re
import time
import cloudscraper
from pywebpush import webpush, WebPushException
import html
import os
import json
from tool import ToolNotify
import traceback
from urllib.parse import urlparse, parse_qs, urljoin, urlencode, urlunparse

site_map = {
    'ppomppu': '뽐뿌',
    'ruriweb': '루리웹',
    'quasarzone' : '퀘이사존'
}
board_map = {
    'ppomppu': '뽐뿌게시판',
    'ppomppu4': '해외뽐뿌',
    'ppomppu8': '알리뽐뿌',
    'money': '재태크포럼',
    '1020': '루리웹핫딜',
    'qb_saleinfo': '퀘존지름'
}
site_board_map = {
    'ppomppu': ['ppomppu', 'ppomppu4', 'ppomppu8', 'money'],
    'ruriweb': ['1020'],
    'quasarzone': ['qb_saleinfo']
}


def get_url_prefix(site_name):
    url_prefix = ''
    if site_name == 'ppomppu':
        url_prefix = 'https://www.ppomppu.co.kr/zboard/'
    elif site_name == 'ruriweb':
        url_prefix = ''
    elif site_name == 'quasarzone':
        url_prefix = ''

    return url_prefix


class ModuleBasic(PluginModuleBase):
    def __init__(self, P):
        super(ModuleBasic, self).__init__(P, name='basic',
                                          first_menu='setting', scheduler_desc="핫딜 알람_hot")
        self.db_default = {
            f'db_version': '2.0',
            f'{self.name}_auto_start': 'False',
            f'{self.name}_interval': '1',
            f'{self.name}_db_delete_day': '7',
            f'{self.name}_db_auto_delete': 'False',
            f'{P.package_name}_item_last_list_option': '',
            f'notify_mode': 'always',
            'use_site_ppomppu': 'False',
            'use_board_ppomppu_ppomppu': 'False',
            'use_board_ppomppu_ppomppu4': 'False',
            'use_board_ppomppu_ppomppu8': 'False',
            'use_board_ppomppu_money': 'False',
            'use_site_ruriweb': 'False',
            'use_board_ruriweb_1020': 'False',
            'use_site_quasarzone': 'False',
            'use_board_quasarzone_qb_saleinfo': 'False',
            'use_hotdeal_alarm': 'False',
            'use_hotdeal_keyword_alarm': 'False',
            'use_hotdeal_keyword_alarm_dist' : 'False',
            'hotdeal_alarm_keyword': '',
            'alarm_message_template': '`{title}`\n{url}\n{mall_url}',
            'selenium_remote_address': '',
            'use_hotdeal_web_push' : 'True',
            'web_push_public_key' : '',
            'web_push_subscription' : '[]'
        }
        self.web_list_model = ModelItem

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        if sub == 'setting':
            arg['is_include'] = F.scheduler.is_include(
                self.get_scheduler_name())
            arg['is_running'] = F.scheduler.is_running(
                self.get_scheduler_name())
        if sub == 'list':
            arg = self.web_list_model.get_list()
        return render_template(f'{P.package_name}_{self.name}_{sub}.html', arg=arg, site_map=site_map, board_map=board_map, site_board_map=site_board_map)

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret': 'success'}
        if command == 'test':
            ret['status'] = 'warn'
            ret['title'] = '테스트'
            ret['data'] = '테스트 내용'
        return jsonify(ret)

    def scheduler_function(self):
        self.scrap_items()

    def _setting_enabled(self, key):
        raw = P.ModelSetting.get(key)
        enabled = str(raw).strip().lower() in ('true', '1', 'yes', 'on')
        P.logger.info('[HOTDEAL][SETTING] key=%s raw=%r enabled=%s', key, raw, enabled)
        return enabled

    def _request_page(self, client, url, site, board, phase):
        started = time.monotonic()
        response = client.get(url, timeout=(10, 30))
        # The supplied ppomppu page declares EUC-KR. Prefer a declared charset.
        charset = re.search(br'charset\s*=\s*["\x27]?([A-Za-z0-9_-]+)', response.content[:8192], re.I)
        if charset:
            response.encoding = charset.group(1).decode('ascii')
        P.logger.info(
            '[HOTDEAL][HTTP] phase=%s site=%s board=%s status=%s bytes=%s '
            'encoding=%s seconds=%.2f path=%s',
            phase, site, board, response.status_code, len(response.content),
            response.encoding, time.monotonic() - started, urlparse(response.url).path,
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _with_query(url, name, value):
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query[name] = [value]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def scrap_detail(self):
        ret = {'status': 'success'}
        items = ModelItem.get_non_shopping_mall_lsit()
        if items is None:
            P.logger.error('[HOTDEAL][DETAIL] DB query failed; see MODEL log')
            ret['status'] = 'error'
            return ret
        P.logger.info('[HOTDEAL][DETAIL] pending=%s', len(items))
        patterns = {
            'ppomppu': r'div class=wordfix>링크: \<a .+\>(?P<mall_url>.+)\</a\>',
            'ruriweb': r'<div class=\"source_url\">원본출처.+<a href=\".+\">(?P<mall_url>.+)</a>',
            'quasarzone': r'<th>링크</th>\s+<td><a href=\".+\"\s+>(?P<mall_url>.+)</a>',
        }
        with requests.Session() as session:
            scraper = None
            for item in items:
                try:
                    regex = patterns.get(item.site_name)
                    mall_url = ''
                    if regex:
                        url = urljoin(get_url_prefix(item.site_name), item.url)
                        client = session
                        if item.site_name == 'quasarzone':
                            if scraper is None:
                                scraper = cloudscraper.create_scraper(browser={
                                    'browser': 'chrome', 'platform': 'android', 'desktop': False,
                                })
                            client = scraper
                            url = self._with_query(url, 'popularity', 'Y')
                        elif item.site_name == 'ruriweb':
                            url = self._with_query(url, 'view_best', '1')
                        else:
                            url = self._with_query(url, 'hotlist_flag', '999')
                        response = self._request_page(client, url, item.site_name, item.board_name, 'detail')
                        match = re.search(regex, response.text)
                        if match:
                            mall_url = match.groupdict().get('mall_url', '')
                        P.logger.info('[HOTDEAL][DETAIL] id=%s site=%s mall_link_found=%s',
                                      item.id, item.site_name, bool(mall_url))
                    item.mall_url = html.unescape(mall_url)
                    ModelItem.save(item)
                except Exception:
                    ret['status'] = 'error'
                    P.logger.error('[HOTDEAL][DETAIL_ERROR] id=%s site=%s\n%s',
                                   item.id, item.site_name, traceback.format_exc())
            if scraper is not None:
                scraper.close()
        return ret

    def scrap_items(self):
        ret = {'status': 'success', 'data': []}
        started = time.monotonic()
        P.logger.info('[HOTDEAL][START] module_file=%s', __file__)
        specs = [
            ('ppomppu', ['ppomppu', 'ppomppu4', 'ppomppu8', 'money'],
             r'class="baseList-title[^"]*"\s+href="(?P<url>view\.php[^"]+)"[^>]*>(?P<title>.*?)</a>',
             re.MULTILINE | re.IGNORECASE | re.DOTALL),
            ('ruriweb', ['1020', '600004'],
             r'<a class=\"deco\" href=\"(?P<url>.+)\"\>(?P<title>.+)</a>', re.MULTILINE),
            ('quasarzone', ['qb_saleinfo'],
             r'<p class=\"tit\">\s+<a href=\"(?P<url>.+)\"\s+class=.+>\s+.+\s+(?:<span class=\"ellipsis-with-reply-cnt\">)?(?P<title>.+?)(?:</span>)',
             re.MULTILINE),
        ]
        with requests.Session() as session:
            scraper = None
            for site, boards, regex, flags in specs:
                if not self._setting_enabled('use_site_' + site):
                    continue
                for board in boards:
                    if not self._setting_enabled('use_board_%s_%s' % (site, board)):
                        continue
                    try:
                        client = session
                        if site == 'ppomppu':
                            url = 'https://www.ppomppu.co.kr/zboard/zboard.php?id=%s&hotlist_flag=999' % board
                        elif site == 'ruriweb':
                            url = 'https://bbs.ruliweb.com/market/board/%s?view_best=1' % board
                        else:
                            url = 'https://quasarzone.com/bbs/%s?popularity=Y' % board
                            if scraper is None:
                                scraper = cloudscraper.create_scraper(browser={
                                    'browser': 'chrome', 'platform': 'android', 'desktop': False,
                                })
                            client = scraper
                        response = self._request_page(client, url, site, board, 'list')
                        matches = list(re.finditer(regex, response.text, flags))
                        accepted = skipped = 0
                        for match in matches:
                            obj = match.groupdict()
                            obj['url'] = html.unescape(obj['url'])
                            if site == 'ppomppu':
                                query = parse_qs(urlparse(obj['url']).query)
                                if query.get('id', [''])[0] != board or not query.get('no', [''])[0].isdigit():
                                    skipped += 1
                                    continue
                            obj['title'] = html.unescape(re.sub(r'<[^>]+>', '', obj['title'])).strip()
                            if not obj['title']:
                                skipped += 1
                                continue
                            if site == 'quasarzone':
                                obj['url'] = urljoin('https://quasarzone.com', obj['url'])
                            obj['site'] = site
                            obj['board'] = board
                            ret['data'].append(obj)
                            accepted += 1
                        P.logger.info('[HOTDEAL][PARSE] site=%s board=%s matched=%s accepted=%s skipped=%s',
                                      site, board, len(matches), accepted, skipped)
                        if not accepted:
                            page_title = re.search(r'<title[^>]*>(.*?)</title>', response.text, re.I | re.S)
                            P.logger.warning('[HOTDEAL][EMPTY] site=%s board=%s page_title=%r '
                                             'has_title_class=%s has_view_link=%s',
                                             site, board,
                                             html.unescape(page_title.group(1)).strip()[:200] if page_title else '',
                                             'baseList-title' in response.text, 'view.php' in response.text)
                    except Exception:
                        ret['status'] = 'error'
                        P.logger.error('[HOTDEAL][BOARD_ERROR] site=%s board=%s\n%s',
                                       site, board, traceback.format_exc())
            if scraper is not None:
                scraper.close()
        saved = duplicates = failed = 0
        for row in ret['data']:
            try:
                result = ModelItem.update({
                    'site_name': row['site'], 'board_name': row['board'],
                    'title': row['title'], 'url': row['url'],
                })
                reason = result.get('reason') if isinstance(result, dict) else None
                if isinstance(result, dict) and result.get('ret') == 'success':
                    saved += 1
                elif reason == 'duplicate':
                    duplicates += 1
                else:
                    failed += 1
                    ret['status'] = 'error'
                    P.logger.error('[HOTDEAL][SAVE_RESULT] site=%s board=%s result=%r',
                                   row['site'], row['board'], result)
            except Exception:
                failed += 1
                ret['status'] = 'error'
                P.logger.error('[HOTDEAL][SAVE_ERROR] site=%s board=%s\n%s',
                               row['site'], row['board'], traceback.format_exc())
        P.logger.info('[HOTDEAL][SAVE_SUMMARY] parsed=%s saved=%s duplicate=%s failed=%s',
                      len(ret['data']), saved, duplicates, failed)
        try:
            self.process_discord_data()
        except Exception:
            ret['status'] = 'error'
            P.logger.error('[HOTDEAL][NOTIFY_ERROR]\n%s', traceback.format_exc())
        P.logger.info('[HOTDEAL][END] status=%s seconds=%.2f', ret['status'], time.monotonic() - started)
        return ret

    def process_discord_data(self):
        try:
            detail_result = self.scrap_detail()
            P.logger.info('[HOTDEAL][DETAIL_SUMMARY] result=%r', detail_result)
        except Exception as e:
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
        items = ModelItem.get_alarm_target_list()
        P.logger.info('[HOTDEAL][NOTIFY] pending=%s', len(items) if items is not None else None)
        P.logger.info('[HOTDEAL][NOTIFY_SETTINGS] always=%s keyword=%s distinct=%s web_push=%s',
                      P.ModelSetting.get_bool('use_hotdeal_alarm'),
                      P.ModelSetting.get_bool('use_hotdeal_keyword_alarm'),
                      P.ModelSetting.get_bool('use_hotdeal_keyword_alarm_dist'),
                      P.ModelSetting.get_bool('use_hotdeal_web_push'))
        if items is None or len(items) == 0:
            return
        msg_template = P.ModelSetting.get('alarm_message_template')
        if msg_template is None or len(msg_template) == 0:
            P.logger.warning('[HOTDEAL][NOTIFY_SKIP] empty message template')
            return
        for item in items:
            if P.ModelSetting.get_bool('use_hotdeal_alarm') or P.ModelSetting.get_bool('use_hotdeal_keyword_alarm'):
                title = item.title.replace('&gt;', '>').replace('&lt;', '<')
                site = site_map[item.site_name]
                board = board_map[item.board_name]
                url = get_url_prefix(site_name=item.site_name)+item.url
                mall_url = item.mall_url if item.mall_url and len(
                    item.mall_url) > 0 else ''
                is_send = False
                is_dist_send = False
                is_web_push = P.ModelSetting.get_bool('use_hotdeal_web_push')

                keywords = P.ModelSetting.get('hotdeal_alarm_keyword').split(',')
                if P.ModelSetting.get_bool('use_hotdeal_alarm'):
                    is_send = True
                else:
                    is_send = False
                    is_dist_send = False
                for keyword in keywords:
                    if P.ModelSetting.get_bool('use_hotdeal_keyword_alarm'):
                        if len(keyword) > 0 and keyword.lower() in title.lower():
                            is_send = True
                    if P.ModelSetting.get_bool('use_hotdeal_keyword_alarm_dist'):
                        if len(keyword) > 0 and keyword.lower() in title.lower():
                            is_dist_send = True
                        

                P.logger.info('[HOTDEAL][NOTIFY_DECISION] id=%s site=%s send=%s distinct=%s',
                              item.id, item.site_name, is_send, is_dist_send)
                if is_send is True:
                    msg = msg_template
                    msg = msg.replace('{title}', title).replace('{site}', site).replace(
                        '{board}', board).replace('{mall_url}', mall_url).replace('{url}', url)
                    ToolNotify.send_message(
                        msg, message_id=f"bot_{P.package_name}")
                    if is_web_push:
                        self.web_push({'message' : title, 'url':mall_url if len(mall_url) > 0 else url})
                if is_dist_send is True:
                    msg = msg_template
                    msg = msg.replace('{title}', title).replace('{site}', site).replace(
                        '{board}', board).replace('{mall_url}', mall_url).replace('{url}', url)
                    ToolNotify.send_message(
                        msg, message_id=f"bot_{P.package_name}_keyword")
                    if is_web_push:
                        self.web_push({'message' : title, 'url':mall_url if len(mall_url) > 0 else url})
            P.logger.info('[HOTDEAL][ALARM_MARK] id=%s alarm_status=True (existing behavior)', item.id)
            item.alarm_status = True
            ModelItem.save(item)
    def process_api(self, sub, req):
        result = ''
        if sub == 'web_push_init':
            if not os.path.exists('/data/web_push'):
                os.mkdir('/data/web_push')
            gen_key_result = os.popen("cd /data/web_push ; /usr/local/bin/vapid --applicationServerKey --gen").read()
            key = gen_key_result.split(' = ')[1].strip()
            P.logger.info(key)
            with open('/data/web_push/key.txt','w') as file:
                file.write(key)
            P.ModelSetting.set('web_push_public_key', key)
            result = json.dumps({'key' : key})

        elif sub =='web_push_subscribe':
            P.logger.info(req.get_json())
            subscription_info = req.get_json()
            web_push_subscription = json.loads(P.ModelSetting.get('web_push_subscription'))
            if type(web_push_subscription) != list:
                web_push_subscription = []
            if subscription_info not in  web_push_subscription:
                web_push_subscription.append(subscription_info)
            P.ModelSetting.set('web_push_subscription', json.dumps(web_push_subscription))
            return subscription_info

        elif sub == 'web_push' : 
            self.web_push(req.get_json())
            result = json.dumps({'status' : 'success'})
        elif sub == 'web_push_reset' :
            P.ModelSetting.set('web_push_subscription', '[]')
        return result
    def web_push(self, data):
        P.logger.info(data)
        infos = json.loads(P.ModelSetting.get('web_push_subscription'))
        result = []
        for info in infos:
            try:
                result.append(webpush(
                    subscription_info = info,
                    data = json.dumps(data),
                    vapid_private_key='/data/web_push/private_key.pem',
                    vapid_claims = {
                        'sub' : 'mailto:dbswnschl@gmail.com'
                    }
                ))
            except:
                P.logger.error(traceback.format_exc())
                continue
