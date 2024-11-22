# -*- coding: utf-8 -*-

# Created by: Raf

import os
import sys
import time
import threading
import pyautogui
import cv2
import numpy as np
from PIL import Image

from PyQt5 import QtGui, QtWidgets, QtCore
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPixmapItem, QInputDialog, QMessageBox
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import QTime, QEventLoop
from MainWindowUI import Ui_Form

from douzero.env.game import GameEnv
from douzero.evaluation.deep_agent import DeepAgent

from pyscreeze import ImageNotFoundException

EnvCard2RealCard = {3: '3', 4: '4', 5: '5', 6: '6', 7: '7',
                    8: '8', 9: '9', 10: 'T', 11: 'J', 12: 'Q',
                    13: 'K', 14: 'A', 17: '2', 20: 'X', 30: 'D'}

RealCard2EnvCard = {'3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
                    '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12,
                    'K': 13, 'A': 14, '2': 17, 'X': 20, 'D': 30}

AllEnvCard = [3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 7, 7, 7, 7,
              8, 8, 8, 8, 9, 9, 9, 9, 10, 10, 10, 10, 11, 11, 11, 11, 12,
              12, 12, 12, 13, 13, 13, 13, 14, 14, 14, 14, 17, 17, 17, 17, 20, 30]

AllCards = ['rD', 'bX', 'b2', 'r2', 'bA', 'rA', 'bK', 'rK', 'bQ', 'rQ', 'bJ', 'rJ', 'bT', 'rT',
            'b9', 'r9', 'b8', 'r8', 'b7', 'r7', 'b6', 'r6', 'b5', 'r5', 'b4', 'r4', 'b3', 'r3']


class MyPyQT_Form(QtWidgets.QWidget, Ui_Form):
    def __init__(self):
        super(MyPyQT_Form, self).__init__()
        self.setupUi(self)
        self.setWindowFlags(QtCore.Qt.WindowMinimizeButtonHint |    # 使能最小化按钮
                            QtCore.Qt.WindowCloseButtonHint |       # 使能关闭按钮
                            QtCore.Qt.WindowStaysOnTopHint)         # 窗体总在最前端
        self.setFixedSize(self.width(), self.height())              # 固定窗体大小
        self.setWindowIcon(QIcon('pics/favicon.ico'))
        window_pale = QtGui.QPalette()
        window_pale.setBrush(self.backgroundRole(), QtGui.QBrush(QtGui.QPixmap("pics/bg.png")))
        self.setPalette(window_pale)

        self.Players = [self.RPlayer, self.Player, self.LPlayer]
        self.counter = QTime()

        # 参数
        self.MyConfidence = 0.9  # 我的牌的置信度
        self.OtherConfidence = 0.9  # 别人的牌的置信度
        # self.WhiteConfidence = 0.9  # 检测白块的置信度
        self.LandlordFlagConfidence = 0.8     # # 检测地主标志的置信度
        self.ThreeLandlordCardsConfidence = 0.9  # 检测地主底牌的置信度
        self.WaitTime = 1  # 等待状态稳定延时
        self.MyFilter = 50  # 我的牌检测结果过滤参数
        self.OtherFilter = 30  # 别人的牌检测结果过滤参数
        self.SleepTime = 0.1  # 循环中睡眠时间

        # 坐标
        self.MyHandCardsPos = (290, 780, 1250, 85)  # 我的截图区域
        self.MyPlayedCardsPos = (700, 530, 600, 200)  # 我的截图区域
        self.LPlayedCardsPos = (410, 300, 500, 300)  # 左边截图区域
        self.RPlayedCardsPos = (980, 300, 500, 300)  # 右边截图区域
        self.LandlordFlagPos = [(1640, 310, 110, 110), (0, 870, 110, 110), (150, 310, 110, 110)]  # 地主标志截图区域(右-我-左)
        self.ThreeLandlordCardsPos = (820, 40, 256, 76)      # 地主底牌截图区域，随后按比例放大至(320,95)

        # 信号量
        self.shouldExit = 0  # 通知上一轮记牌结束
        self.canRecord = threading.Lock()  # 开始记牌

        # 模型路径
        self.card_play_model_path_dict = {
            'landlord': "baselines/douzero_WP/landlord.ckpt",
            'landlord_up': "baselines/douzero_WP/landlord_up.ckpt",
            'landlord_down': "baselines/douzero_WP/landlord_down.ckpt"
        }

    def init_display(self):
        self.WinRate.setText("胜率：--%")
        self.InitCard.setText("开始")
        self.UserHandCards.setText("手牌")
        self.LPlayedCard.setText("上家出牌区域")
        self.RPlayedCard.setText("下家出牌区域")
        self.PredictedCard.setText("AI出牌区域")
        self.ThreeLandlordCards.setText("三张底牌")
        for player in self.Players:
            player.setStyleSheet('background-color: rgba(255, 0, 0, 0);')

    def init_cards(self):
        # 玩家手牌
        self.user_hand_cards_real = ""
        self.user_hand_cards_env = []
        # 其他玩家出牌
        self.other_played_cards_real = ""
        self.other_played_cards_env = []
        # 其他玩家手牌（整副牌减去玩家手牌，后续再减掉历史出牌）
        self.other_hand_cards = []
        # 三张底牌
        self.three_landlord_cards_real = ""
        self.three_landlord_cards_env = []
        # 玩家角色代码：0-地主上家, 1-地主, 2-地主下家
        self.user_position_code = None
        self.user_position = ""
        # 开局时三个玩家的手牌
        self.card_play_data_list = {}
        # 出牌顺序：0-玩家出牌, 1-玩家下家出牌, 2-玩家上家出牌
        self.play_order = 0

        self.env = None

        # 识别玩家手牌
        self.user_hand_cards_real = self.find_my_cards(self.MyHandCardsPos)
        self.UserHandCards.setText(self.user_hand_cards_real)
        self.user_hand_cards_env = [RealCard2EnvCard[c] for c in list(self.user_hand_cards_real)]
        # 识别三张底牌
        self.three_landlord_cards_real = self.find_three_landlord_cards(self.ThreeLandlordCardsPos)
        self.ThreeLandlordCards.setText("底牌：" + self.three_landlord_cards_real)
        self.three_landlord_cards_env = [RealCard2EnvCard[c] for c in list(self.three_landlord_cards_real)]
        # 识别玩家的角色
        self.user_position_code = self.find_landlord(self.LandlordFlagPos)
        if self.user_position_code is None:
            items = ("地主上家", "地主", "地主下家")
            item, okPressed = QInputDialog.getItem(self, "选择角色", "未识别到地主，请手动选择角色:", items, 0, False)
            if okPressed and item:
                self.user_position_code = items.index(item)
            else:
                return
        self.user_position = ['landlord_up', 'landlord', 'landlord_down'][self.user_position_code]
        for player in self.Players:
            player.setStyleSheet('background-color: rgba(255, 0, 0, 0);')
        self.Players[self.user_position_code].setStyleSheet('background-color: rgba(255, 0, 0, 0.1);')

        # import ipdb; ipdb.set_trace()
        # 整副牌减去玩家手上的牌，就是其他人的手牌,再分配给另外两个角色（如何分配对AI判断没有影响）
        for i in set(AllEnvCard):
            self.other_hand_cards.extend([i] * (AllEnvCard.count(i) - self.user_hand_cards_env.count(i)))
        self.card_play_data_list.update({
            'three_landlord_cards': self.three_landlord_cards_env,
            ['landlord_up', 'landlord', 'landlord_down'][(self.user_position_code + 0) % 3]:
                self.user_hand_cards_env,
            ['landlord_up', 'landlord', 'landlord_down'][(self.user_position_code + 1) % 3]:
                self.other_hand_cards[0:17] if (self.user_position_code + 1) % 3 != 1 else self.other_hand_cards[17:],
            ['landlord_up', 'landlord', 'landlord_down'][(self.user_position_code + 2) % 3]:
                self.other_hand_cards[0:17] if (self.user_position_code + 1) % 3 == 1 else self.other_hand_cards[17:]
        })
        print(self.card_play_data_list)
        # 生成手牌结束，校验手牌数量
        if len(self.card_play_data_list["three_landlord_cards"]) != 3:
            QMessageBox.critical(self, "底牌识别出错", "底牌必须是3张！", QMessageBox.Yes, QMessageBox.Yes)
            self.init_display()
            return
        if len(self.card_play_data_list["landlord_up"]) != 17 or \
            len(self.card_play_data_list["landlord_down"]) != 17 or \
            len(self.card_play_data_list["landlord"]) != 20:
            QMessageBox.critical(self, "手牌识别出错", "初始手牌数目有误", QMessageBox.Yes, QMessageBox.Yes)
            self.init_display()
            return
        # 得到出牌顺序
        self.play_order = 0 if self.user_position == "landlord" else 1 if self.user_position == "landlord_up" else 2

        # 创建一个代表玩家的AI
        ai_players = [0, 0]
        ai_players[0] = self.user_position
        ai_players[1] = DeepAgent(self.user_position, self.card_play_model_path_dict[self.user_position])

        self.env = GameEnv(ai_players)

        self.start()

    def start(self):
        self.env.card_play_init(self.card_play_data_list)
        print("开始出牌\n")
        while not self.env.game_over:
            # 玩家出牌时就通过智能体获取action，否则通过识别获取其他玩家出牌
            if self.play_order == 0:
                print("0")
                self.PredictedCard.setText("...")
                action_message = self.env.step(self.user_position)
                # 更新界面
                self.UserHandCards.setText("手牌：" + str(''.join(
                    [EnvCard2RealCard[c] for c in self.env.info_sets[self.user_position].player_hand_cards]))[::-1])

                self.PredictedCard.setText(action_message["action"] if action_message["action"] else "不出")
                self.WinRate.setText("胜率：" + action_message["win_rate"])
                print("\n手牌：", str(''.join(
                        [EnvCard2RealCard[c] for c in self.env.info_sets[self.user_position].player_hand_cards])))
                print("出牌：", action_message["action"] if action_message["action"] else "不出", "， 胜率：",
                      action_message["win_rate"])
                # 玩家出牌成功后，下家的出牌位置才会清空。如果下家清空，则说明玩家已经出牌。但是该循环0.1秒，若对方出牌太快，则会死循环
                while self.play_card(self.MyPlayedCardsPos) == 0 and \
                        not pyautogui.locateOnScreen('pics/pass.png',
                                                 region=self.MyPlayedCardsPos,
                                                 confidence=self.LandlordFlagConfidence):
                    print("等待玩家出牌")
                    self.counter.restart()
                    while self.counter.elapsed() < 100:
                        QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)
                self.play_order = 1
            elif self.play_order == 1:
                print("1")
                self.RPlayedCard.setText("...")
                pass_flag = None
                # 每0.1秒检查一次下家有没有出牌
                while self.play_card(self.RPlayedCardsPos) == 0 and \
                        not pyautogui.locateOnScreen('pics/pass.png',
                                                     region=self.RPlayedCardsPos,
                                                     confidence=self.LandlordFlagConfidence):
                    print("等待下家出牌")
                    self.counter.restart()
                    while self.counter.elapsed() < 100:
                        QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)
                self.counter.restart()
                # 这边要卡1秒
                while self.counter.elapsed() < 1000:
                    QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)
                # 不出
                pass_flag = pyautogui.locateOnScreen('pics/pass.png',
                                                     region=self.RPlayedCardsPos,
                                                     confidence=self.LandlordFlagConfidence)
                # 未找到"不出"
                if pass_flag is None:
                    # 识别下家出牌
                    self.other_played_cards_real = self.find_other_cards(self.RPlayedCardsPos)
                # 找到"不出"
                else:
                    self.other_played_cards_real = ""
                print("\n下家出牌："+self.other_played_cards_real)
                self.other_played_cards_env = [RealCard2EnvCard[c] for c in list(self.other_played_cards_real)]
                self.env.step(self.user_position, self.other_played_cards_env)
                # 更新界面
                self.RPlayedCard.setText(self.other_played_cards_real if self.other_played_cards_real else "不出")
                self.play_order = 2
            elif self.play_order == 2:
                print("2")
                self.LPlayedCard.setText("...")
                while self.play_card(self.LPlayedCardsPos) == 0 and \
                        not pyautogui.locateOnScreen('pics/pass.png',
                                                    region=self.LPlayedCardsPos,
                                                    confidence=self.LandlordFlagConfidence):
                    print("等待上家出牌")
                    self.counter.restart()
                    while self.counter.elapsed() < 100:
                        QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)
                self.counter.restart()
                while self.counter.elapsed() < 1000:
                    QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)
                # 不出
                pass_flag = pyautogui.locateOnScreen('pics/pass.png',
                                                     region=self.LPlayedCardsPos,
                                                     confidence=self.LandlordFlagConfidence)
                # 未找到"不出"
                if pass_flag is None:
                    # 识别上家出牌
                    self.other_played_cards_real = self.find_other_cards(self.LPlayedCardsPos)
                # 找到"不出"
                else:
                    self.other_played_cards_real = ""
                print("\n上家出牌："+self.other_played_cards_real)
                self.other_played_cards_env = [RealCard2EnvCard[c] for c in list(self.other_played_cards_real)]
                self.env.step(self.user_position, self.other_played_cards_env)
                self.play_order = 0
                # 更新界面
                self.LPlayedCard.setText(self.other_played_cards_real if self.other_played_cards_real else "不出")
            else:
                pass

            self.counter.restart()
            while self.counter.elapsed() < 100:
                QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)

        print("{}胜，本局结束!\n".format("农民" if self.env.winner == "farmer" else "地主"))
        QMessageBox.information(self, "本局结束", "{}胜！".format("农民" if self.env.winner == "farmer" else "地主"),
                                QMessageBox.Yes, QMessageBox.Yes)
        self.env.reset()
        self.init_display()

    def find_landlord(self, landlord_flag_pos):
        for pos in landlord_flag_pos:
            try:
                result = pyautogui.locateOnScreen('pics/landlord_words.png', region=pos, confidence=self.LandlordFlagConfidence)
            except pyautogui.ImageNotFoundException:
                result = None

            if result is not None:
                # import ipdb; ipdb.set_trace()
                return landlord_flag_pos.index(pos)
        return None

    def find_three_landlord_cards(self, pos):
        three_landlord_cards_real = ""
        img = pyautogui.screenshot(region=pos)
        img = img.resize((320,95))
        img_rmasked = self.masked(img,colour='R')
        img_bmasked = self.masked(img,colour='B')
        # import ipdb; ipdb.set_trace()
        for card in AllCards:
            if card[0]=='r':
                target = img_bmasked
            else:
                target = img_rmasked
            result = pyautogui.locateAll(needleImage='pics/o' + card + '.png', haystackImage=target, confidence=self.ThreeLandlordCardsConfidence,grayscale=True)
            try:
                location = list(result)
            except ImageNotFoundException:
                location = []
            three_landlord_cards_real += card[1] * self.cards_filter(location, self.OtherFilter)   
        '''
        for card in AllCards:
            result = pyautogui.locateAll(needleImage='pics/m' + card + '.png', haystackImage=img,
                                         confidence=self.ThreeLandlordCardsConfidence)
            three_landlord_cards_real += card[1] * self.cards_filter(list(result), self.OtherFilter)
        '''
        print("three_landlord_cards_real:"+three_landlord_cards_real)
        return three_landlord_cards_real

    def find_my_cards(self, pos):
        user_hand_cards_real = ""
        img = pyautogui.screenshot(region=pos)
        img_rmasked = self.masked(img,colour='R')
        img_bmasked = self.masked(img,colour='B')
        # img_rmasked.show()
        # img_bmasked.show()
        for card in AllCards:
            if card[0]=='r':
                target = img_bmasked
            else:
                target = img_rmasked
            result = pyautogui.locateAll(needleImage='pics/m' + card + '.png', haystackImage=target, confidence=self.MyConfidence,grayscale=True)
            try:
                location = list(result)
            except ImageNotFoundException:
                location = []
            user_hand_cards_real += card[1] * self.cards_filter(location, self.MyFilter)        
        return user_hand_cards_real
    
    def masked(self,img:Image,colour):

        img_gray = img.convert('L')
        image_array = np.array(img_gray)
        if colour=='R':
            for i in range(image_array.shape[0]):
                for j in range(image_array.shape[1]):
                    if 90>image_array[i][j]>70:
                        image_array[i][j]=233
        else:
           for i in range(image_array.shape[0]):
                for j in range(image_array.shape[1]):
                    if 40>image_array[i][j]>20:
                        image_array[i][j]=233
        
        return Image.fromarray(image_array)
            
            
        
    def find_other_cards(self, pos):
        other_played_cards_real = ""

        self.counter.restart()
        while self.counter.elapsed() < 500:
            QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)

        img = pyautogui.screenshot(region=pos)
        img_rmasked = self.masked(img,colour='R')
        img_bmasked = self.masked(img,colour='B')
        for card in AllCards:
            if card[0]=='r':
                target = img_bmasked
            else:
                target = img_rmasked
            result = pyautogui.locateAll(needleImage='pics/o' + card + '.png', haystackImage=target,
                                         confidence=self.OtherConfidence,grayscale=True)
            other_played_cards_real += card[1] * self.cards_filter(list(result), self.OtherFilter)
        return other_played_cards_real

    def cards_filter(self, location, distance):  # 牌检测结果滤波，去除重复卡牌
        if len(location) == 0:
            return 0
        locList = [location[0][0]]
        count = 1
        for e in location:
            flag = 1  # “是新的”标志
            for have in locList:
                if abs(e[0] - have) <= distance:
                    flag = 0
                    break
            if flag:
                count += 1
                locList.append(e[0])
        return count

    def play_card(self, pos):  # 是否出牌
        other_played_cards_real = ""
        '''
        self.counter.restart()
        while self.counter.elapsed() < 500:
            QtWidgets.QApplication.processEvents(QEventLoop.AllEvents, 50)
        '''
        img = pyautogui.screenshot(region=pos)
        img_rmasked = self.masked(img,colour='R')
        img_bmasked = self.masked(img,colour='B')
        for card in AllCards:
            if card[0]=='r':
                target = img_bmasked
            else:
                target = img_rmasked
            result = pyautogui.locateAll(needleImage='pics/o' + card + '.png', haystackImage=target,
                                         confidence=self.OtherConfidence,grayscale=True)
            other_played_cards_real += card[1] * self.cards_filter(list(result), self.OtherFilter)
        
        if other_played_cards_real == "":
            return 0
        else:
            return 1
        
        
        '''
        result = pyautogui.locateOnScreen('pics/white.png', region=pos, confidence=self.WhiteConfidence)
        if result is None:
            return 0
        else:
            return 1
        '''

    def stop(self):
        try:
            self.env.game_over = True
        except AttributeError as e:
            pass 
            


if __name__ == '__main__':

    # os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
    # os.environ["CUDA_VISIBLE_DEVICES"] = '0'
    os.environ["GIT_PYTHON_REFRESH"] = 'quiet'

    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet("""
    QPushButton{
        text-align : center;
        background-color : white;
        font: bold;
        border-color: gray;
        border-width: 2px;
        border-radius: 10px;
        padding: 6px;
        height : 14px;
        border-style: outset;
        font : 14px;
    }
    QPushButton:hover{
        background-color : light gray;
    }
    QPushButton:pressed{
        text-align : center;
        background-color : gray;
        font: bold;
        border-color: gray;
        border-width: 2px;
        border-radius: 10px;
        padding: 6px;
        height : 14px;
        border-style: outset;
        font : 14px;
        padding-left:9px;
        padding-top:9px;
    }
    QComboBox{
        background:transparent;
        border: 1px solid rgba(200, 200, 200, 100);
        font-weight: bold;
    }
    QComboBox:drop-down{
        border: 0px;
    }
    QComboBox QAbstractItemView:item{
        height: 30px;
    }
    QLabel{
        background:transparent;
        font-weight: bold;
    }
    """)
    my_pyqt_form = MyPyQT_Form()
    my_pyqt_form.show()
    sys.exit(app.exec_())
