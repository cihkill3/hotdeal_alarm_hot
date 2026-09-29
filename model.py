from .setup import *
import traceback
from sqlalchemy import and_, desc, func, not_, or_


class ModelItem(ModelBase):
    P = P
    __tablename__ = 'hotdeal_alarm_hot'
    __table_args__ = {'mysql_collate': 'utf8_general_ci'}
    __bind_key__ = P.package_name
    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime)
    site_name = db.Column(db.String)
    board_name = db.Column(db.String)
    url = db.Column(db.String)
    title = db.Column(db.String)
    alarm_status = db.Column(db.Boolean)
    mall_url = db.Column(db.String)

    def __init__(self):
        self.created_time = datetime.now()
        self.alarm_status = False

    @classmethod
    def update(cls, data):
        # Preserve the existing URL-based duplicate check and return contract.
        cls.P.logger.info('[HOTDEAL][MODEL_CHECK] site=%s board=%s url=%s title=%r',
                          data.get('site_name'), data.get('board_name'),
                          data.get('url'), data.get('title'))
        try:
            if 'id' in data:
                already_item = cls.get_by_id(data['id'])
            else:
                already_item = cls.get_by_url(data['url'])
            if already_item is None:
                cls.P.logger.error('[HOTDEAL][MODEL_QUERY_FAILED] url=%s', data.get('url'))
                return {'ret': 'error', 'msg': 'DB 조회 실패', 'reason': 'query_failed'}
            if already_item:
                cls.P.logger.info('[HOTDEAL][MODEL_DUPLICATE] url=%s existing=%s',
                                  data['url'], len(already_item))
                return {'ret': 'error', 'msg': '이미 존재하는 URL', 'reason': 'duplicate'}
            db_item = ModelItem()
            db_item.board_name = data['board_name']
            db_item.site_name = data['site_name']
            db_item.title = data['title']
            db_item.url = data['url']
            db_item.alarm_status = data.get('alarm_status', False)
            db_item.save()
            cls.P.logger.info('[HOTDEAL][MODEL_SAVED] id=%s site=%s board=%s url=%s',
                              db_item.id, db_item.site_name, db_item.board_name, db_item.url)
            return {'ret': 'success', 'msg': '업데이트 하였습니다.', 'reason': 'created'}
        except Exception:
            cls.P.logger.error('[HOTDEAL][MODEL_ERROR] url=%s\n%s',
                               data.get('url'), traceback.format_exc())
            try:
                with F.app.app_context():
                    F.db.session.rollback()
            except Exception:
                cls.P.logger.error('[HOTDEAL][MODEL_ROLLBACK_ERROR]\n%s', traceback.format_exc())
            return {'ret': 'error', 'msg': 'DB 저장 실패', 'reason': 'exception'}

    @classmethod
    def get_list(cls):
        ret = super().get_list(by_dict=True)
        return ret

    @classmethod
    def get_non_shopping_mall_lsit(cls):
        try:
            with F.app.app_context():
                query = F.db.session.query(cls).filter_by(mall_url=None)
                return query.all()

        except Exception as e:
            cls.P.logger.error(f'Exception:{str(e)}')
            cls.P.logger.error(traceback.format_exc())

    @classmethod
    def get_alarm_target_list(cls):
        try:
            with F.app.app_context():
                query = F.db.session.query(cls).filter_by(alarm_status=False)
                return query.all()

        except Exception as e:
            cls.P.logger.error(f'Exception:{str(e)}')
            cls.P.logger.error(traceback.format_exc())

    @classmethod
    def get_by_id(cls, id):
        try:
            with F.app.app_context():
                query = F.db.session.query(cls).filter_by(id=id)
                query = query.order_by(desc(cls.created_time))
                return query.all()

        except Exception as e:
            cls.P.logger.error(f'Exception:{str(e)}')
            cls.P.logger.error(traceback.format_exc())

    @classmethod
    def get_by_url(cls, url):
        try:
            with F.app.app_context():
                query = F.db.session.query(cls).filter_by(url=url)
                query = query.order_by(desc(cls.created_time))
                return query.all()

        except Exception as e:
            cls.P.logger.error(f'Exception:{str(e)}')
            cls.P.logger.error(traceback.format_exc())

    @classmethod
    def make_query(cls, req, order='desc', search='', option1='all', option2='all'):
        with F.app.app_context():
            query = cls.make_query_search(
                F.db.session.query(cls), search, cls.title)

            if option1 != 'all':
                query = query.filter(cls.site_name == option1)

            if option2 != 'all':
                query = query.filter(cls.board_name == option2)

            if order == 'desc':
                query = query.order_by(desc(cls.created_time))
            else:
                query = query.order_by(cls.created_time)

            return query
