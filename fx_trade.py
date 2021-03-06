
# coding: utf-8

# In[ ]:


import gym
import gym.spaces
import numpy as np
import datetime as dt
import time
from action import Action
from position import Position


# In[ ]:


class FXTrade(gym.core.Env):
    THRESHOULD_TIME_DELTA = dt.timedelta(days=1)
    
    def __init__(self, initial_cash, spread, hist_data, seed_value=100000, logger=None, amount_unit=10000):
        self.hist_data = hist_data
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.spread = spread
        self._positions = []
        self._seed = seed_value
        self._logger = logger
        self.amount_unit = amount_unit
        np.random.seed(seed_value)
        
        # x軸: N番目の足（時間経過）, y軸: 現在の1USDの価格（単位：円）
        high = np.array([self.hist_data.steps(), hist_data.data()['Close'].max()]) # [x軸最大値, y軸最大値]
        low = np.array([0, hist_data.data()['Close'].min()]) # [x軸最小値, y軸最小値]
        self.action_space = gym.spaces.Discrete(len(Action)) # Actionクラスで定義 買う、売る、なにもしないの3択
        self.observation_space = gym.spaces.Box(low = low, high = high) # [N番目の足, Close price]

    def get_now_datetime_as(self, datetime_or_float):
        if datetime_or_float == 'float':
            return self._now_datetime
        else:
            dt = self._float2datetime(self._now_datetime)
            return dt
    
    def _set_now_datetime(self, value):
        if isinstance(value, float):
            assert self._min_date <= value, value
            assert value <= self._max_date, value
            self._now_datetime = value
            return value
        else:
            assert self._min_date <= self._datetime2float(value), '%f <= %f, %s' % (self._min_date, self._datetime2float(value), value)
            assert self._datetime2float(value) <= self._max_date, '%f <= %f, %s' % (self._datetime2float(value), self._max_date, value)
            float_val = self._datetime2float(value)
            self._now_datetime = float_val
            return float_val
            
    def setseed(self, seed_value):
        self._seed = seed_value
        self._logger.info('Set seed value: %d' % self._seed)
        return seed_value
        
    def _seed(self):
        return self._seed
    
    #def _datetime2float(self, datetime64_value):
    #    try:
    #        float_val = float(str(datetime64_value.astype('uint64'))[:10])
    #        return float_val
    #    except:
    #        self._logger.error('_datetime2float except')
    #        import pdb; pdb.set_trace()
    #
    #def _float2datetime(self, float_timestamp):
    #    try:
    #        datetime_val = np.datetime64(dt.datetime.utcfromtimestamp(float_timestamp))
    #        return datetime_val
    #    except:
    #        self._logger.error('_float2datetime except')
    #        import pdb; pdb.set_trace()
    
    ''' 評価額を計算する '''
    def _calc_total_estimated_value(self, now_buy_price, now_sell_price):
        positions_buy_or_sell = None
        if self._positions:
            self._logger.info('現在の評価額を再計算')
            positions_buy_or_sell = self._positions[0].buy_or_sell
            self._logger.info('buy_or_sell: %d' % positions_buy_or_sell)
        else:
            positions_buy_or_sell = None
        self._logger.info('positions_buy_or_sell: %s', positions_buy_or_sell)
        now_price_for_positions = self._get_price_of(positions_buy_or_sell, now_buy_price, now_sell_price)
        
        if not self._positions: # positions is empty
            return 0
        total_estimated_value = 0
        for position in self._positions:
            total_estimated_value += position.estimated_value(now_price_for_positions)
        return total_estimated_value
    
    ''' 全ポジションを決済する '''
    def _close_all_positions_by(self, now_price):
        total_estimated_value = 0
        buy_or_sell = self._positions[0].buy_or_sell
        
        for position in self._positions:
            total_estimated_value += position.estimated_value(now_price)
        self._positions = []
        self.cash += total_estimated_value
        return total_estimated_value
        
    ''' 注文を出す '''
    def _order(self, buy_or_sell, now_price, amount):
        required_cash = now_price * amount
        # 簡単にするために、以下のロジックはスキップする
        #if required_cash > self.cash: # 手持ちの現金で買えなければ、買わない
        #    return None
        position = Position(buy_or_sell=buy_or_sell, price=now_price, amount=amount)
        self._positions.append(position)
        self.cash -= required_cash
        return position
    
    ''' 参照すべき価格を返す。取引しようとしているのが売りか買いかで判断する。 '''
    # 簡単にするため、一時的に売値も買値も同じ額とする
    def _get_price_of(self, buy_or_sell, now_buy_price, now_sell_price):
        return now_buy_price
        # if buy_or_sell == Action.BUY.value or buy_or_sell == Action.STAY.value:
        #     return now_buy_price
        # elif buy_or_sell == Action.SELL.value:
        #     return now_sell_price
        # else:
        #     return None

    ''' 今注目している日時を1つ進める（次の足を見る） '''
    def _increment_datetime(self):
        self._logger.info('今注目している日時を更新 (=インデックスのインクリメント)')
        before_datetime = self.hist_data.date_at(self._now_index)
        self._logger.info('  before: %06d [%s]' % (self._now_index, before_datetime))
        self._now_index += 1
        try:
            after_datetime = self.hist_data.date_at(self._now_index)
            self._logger.info('   after: %06d [%s]' % (self._now_index, after_datetime))
        except:
            self._logger.info('   after: END OF DATA')
        
    ''' For Debug: 毎日00:00に買値を表示する。学習の進捗を確認するため。 '''
    def print_info_if_a_day_begins(self, now_datetime, now_buy_price):
        if now_datetime.hour == 0 and now_datetime.minute == 0:
            self._logger.info('%s %f' % (now_datetime, now_buy_price))
    
    ''' ポジションの手仕舞い、または追加オーダーをする '''
    def _close_or_more_order(self, buy_or_sell_or_stay, now_price):
        if not self._positions: # position is empty
            if buy_or_sell_or_stay != Action.STAY.value:
                self._order(buy_or_sell_or_stay,
                            now_price=now_price, amount=self.amount_unit)
        else: # I have positions
            if buy_or_sell_or_stay == Action.BUY.value:
                reverse_action = Action.SELL.value
            elif buy_or_sell_or_stay == Action.SELL.value:
                reverse_action = Action.BUY.value

            if self._positions[0].buy_or_sell == reverse_action:
                # ポジションと逆のアクションを指定されれば、手仕舞い
                self._close_all_positions_by(now_price)
            else:
                # 追加オーダー
                self._order(buy_or_sell_or_stay,
                            now_price=now_price, amount=self.amount_unit)
        
    ''' 各stepごとに呼ばれる
        actionを受け取り、次のstateとreward、episodeが終了したかどうかを返すように実装 '''
    def _step(self, action):
        self._logger.info('_step %08d STARTED' % self._now_index)
        
        # actionを受け取り、次のstateを決定
        buy_or_sell_or_stay = action
        assert buy_or_sell_or_stay == Action.SELL.value or             buy_or_sell_or_stay == Action.STAY.value or             buy_or_sell_or_stay == Action.BUY.value, 'buy_or_sell_or_stay: %d' % buy_or_sell_or_stay
        
        # ポジションの手仕舞い、または追加オーダーをする
        values_at_this_index = self.hist_data.values_at(self._now_index)
        # 簡単にするため、スプレッドは一旦考えない
        now_price = now_sell_price = now_buy_price = values_at_this_index.Close[0]
        self._close_or_more_order(buy_or_sell_or_stay, now_buy_price)
        
        # 現在の評価額の合計値を再計算
        total_estimated_value = self._calc_total_estimated_value(now_buy_price, now_sell_price)

        # For Debug: 毎日00:00に買値を表示する。学習の進捗を確認するため。
        now_datetime = values_at_this_index.index[0]
        self.print_info_if_a_day_begins(now_datetime, now_buy_price)
        
        # 報酬は現金と総評価額から初期現金を引いたもの（未実現利益＋実現利益）
        reward = total_estimated_value + self.cash - self.initial_cash
        self._logger.info('reward: %f', reward)

        # 日付が学習データの最後と一致するか、含み損が初期の現金の1割以上で終了
        done = self._now_index >= self.hist_data.steps() or                 ((-reward) >= self.initial_cash * 0.1)
        if done:
            self._logger.info('Finished (done==True)')
            self._logger.info('now_datetime: %s' % now_datetime)
            self._logger.info('len(self.hist_data.data()) - 1: %d' % self.hist_data.steps())
        
        # 今注目している日時を更新
        self._increment_datetime()
        
        # その時点における値群
        if self._now_index >= self.hist_data.steps():
            done = True
            next_buy_price = 0
        else:
            try:
                next_buy_price = self.hist_data.close_at(self._now_index)
            except IndexError as e:
                # ここに到達するはずはないが、念のため
                done = True
                self._logger.critical('IndexError %s' % e)
            
        # 次のアクションが未定のため、買値を渡す
        # now_sell_price = now_buy_price - self.spread
        # 
        # # actionによって、使用する価格を変える（売価/買価）
        # now_price = self._get_price_of(buy_or_sell_or_stay,
        #                                now_buy_price = now_buy_price,
        #                                now_sell_price = now_sell_price)
        
        # 次のstate、reward、終了したかどうか、追加情報の順に返す
        # 追加情報は特にないので空dict
        self._logger.info('_step ENDED')
        return np.array([self._now_index, next_buy_price]), reward, done, {}
        
    ''' 各episodeの開始時に呼ばれ、初期stateを返すように実装 '''
    def _reset(self):
        self._logger.info('_reset START')
        self._logger.info('self._seed: %i' % self._seed)
        initial_index = 0
        
        self._logger.info('Start datetime: %s' % self.hist_data.date_at(initial_index))
        now_buy_price = self.hist_data.data().ix[[initial_index], ['Close']].Close.iloc[0]
        self._now_index = initial_index
        self._positions = []
        self.cash = self.initial_cash
        self._logger.info('_reset END')
        next_state = now_buy_price
        return np.array([0, next_state])
    

