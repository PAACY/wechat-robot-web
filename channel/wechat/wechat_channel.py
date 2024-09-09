# encoding:utf-8

"""
wechat channel
"""

import io
import json
import os
import threading
import time

import requests

from bridge.context import *
from bridge.reply import *
from channel.chat_channel import ChatChannel
from channel import chat_channel
from channel.wechat.wechat_message import *
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.time_check import time_checker
from config import conf, get_appdata_dir
from lib import itchat
from lib.itchat.content import *

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# engine = create_engine('sqlite:///example.db', echo=True)
engine = create_engine('sqlite:///example.db')
Base = declarative_base()

class Techclienttable(Base):
    __tablename__ = 'techclienttable'
    id = Column(Integer, primary_key=True, unique=True, autoincrement=True)
    techgroup = Column(String(255), nullable=False)
    techname = Column(String(255), nullable=False)
    clientname = Column(String(255), nullable=False)

class Techgroup(Base):
    __tablename__ = 'techcgroup'
    id = Column(Integer, primary_key=True, unique=True, autoincrement=True)
    techgroupname = Column(String(255), nullable=False)

class Clientcgroup(Base):
    __tablename__ = 'clientcgroup'
    id = Column(Integer, primary_key=True, unique=True, autoincrement=True)
    clientgroupname = Column(String(255), nullable=False)

class DictTable(Base):
    __tablename__ = 'dicttable'
    id = Column(Integer, primary_key=True, unique=True, autoincrement=True)
    Nickname = Column(String(255), nullable=False)
    Username = Column(String(255), nullable=False)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()


# 前面的毫无改动
from threading import Timer

# 定义一个dict，保存消息体
msg_dict = {}
# 定义一个list，保存要撤回的消息类型
# msg_type_listen = ['Text', 'Picture', 'Video', 'Attachment']
# 定义接收撤回消息的好友
target_friend = None
# 已接收消息的字典
receivedMsgs1 = {}

def get_revoke_msg_receiver():
    global target_friend  # 声明target_friend是全局变量
    friends = itchat.get_friends(update=True)
    groups = itchat.get_chatrooms(update=True)
    contact = itchat.get_contact(update=True)
    itchat.accept_friend()
    for friend in groups:
        if friend['NickName'] == '123测试':  # 替换为要发送到的好友的昵称
            target_friend = friend
            break
    return target_friend

# 捕获撤回消息的提醒，查找旧消息并回复
def revoke_msg(msg, is_group=False):
    match = re.search('撤回了一条消息', msg['Content'])
    if match:
        # 从撤回消息里提取被撤回的消息的msg_id
        old_msg_id = re.search(r"\<msgid\>(.*?)\<\/msgid\>", msg['Content']).group(1)
        # 判断被撤回消息的msg_id在不在已收取的消息里
        if old_msg_id in msg_dict.keys():
            old_msg = msg_dict[old_msg_id]
            if target_friend is None:
                get_revoke_msg_receiver()  # 更新全局变量target_friend
            # 原消息是文本消息
            if old_msg['Type'] == 'Text':
                old_msg_text = old_msg['Text']
                if is_group:
                    itchat.send(msg='群：【'+msg['User']['NickName']+'】的【'+msg['ActualNickName'] + '】刚刚发过这条消息：' + old_msg_text,
                                toUserName=target_friend['UserName'])
                else:
                    itchat.send(msg='【'+msg['User']['NickName'] + '】刚刚发过这条消息：' + old_msg_text,
                                toUserName=target_friend['UserName'])
                    # 原消息是需要下载的文件消息
            elif old_msg['Type'] in ['Picture', 'Video', 'Attachment', 'Recording']:
                # 发送文本消息给自己
                msg_type = {'Picture': '图片', 'Video': '视频', 'Attachment': '文件', 'Recording': '语音'}[
                    old_msg['Type']]
                if is_group:
                    itchat.send_msg(
                        msg=f'群：【{msg["User"]["NickName"]}】的【{msg["ActualNickName"]}】刚刚发过这条{msg_type}👇',
                        toUserName=target_friend['UserName'])
                else:
                    itchat.send_msg(msg=f'【{msg["User"]["NickName"]}】刚刚发过这条{msg_type}👇',
                                    toUserName=target_friend['UserName'])
                # 发送文件
                file_info = msg_dict[old_msg_id]['FileName']
                if old_msg['Type'] == 'Picture':
                    itchat.send_image(file_info, toUserName=target_friend['UserName'])
                elif old_msg['Type'] == 'Video':
                    itchat.send_video(file_info, toUserName=target_friend['UserName'])
                elif old_msg['Type'] == 'Recording':
                    itchat.send_file(file_info, toUserName=target_friend['UserName'])
                else:
                    itchat.send_file(file_info, toUserName=target_friend['UserName'])

# 定时清理过期消息
out_date_msg_dict = []
# 过期时间，正常是120秒，测试的时候可以少一点
out_date_time = 120
# 删除间隔时间
delete_cycle_time = 2

def delete_out_date_msg():
    # 遍历存储消息的dict里，找出过期的消息
    for m in msg_dict:
        current_time = time.time()
        current_time_int = int(current_time)
        if (current_time_int - msg_dict[m]['CreateTime']) > out_date_time:
            out_date_msg_dict.append(m)
    # 用已存储在list里的过期消息的key，删除dict里的消息
    for n in out_date_msg_dict:
        # 文本消息只要删掉dict里的消息
        if msg_dict[n]['Type'] == 'Text':
            msg_dict.pop(n)
        # 文件消息要额外删掉文件
        elif msg_dict[n]['Type'] in ['Picture', 'Video', 'Attachment', 'Recording']:
            os.remove(msg_dict[n]['FileName'])
            msg_dict.pop(n)
    # 清空存储过期消息key的list，为下一次遍历做准备
    out_date_msg_dict.clear()
    t = Timer(delete_cycle_time, delete_out_date_msg)
    t.start()

delete_out_date_msg()

# 消息检查装饰器
def _msg_check(func):
    def wrapper(msg, is_group):
        msgId = msg['MsgId']
        if msgId in receivedMsgs1:
            logger.info("Wechat message {} already received, ignore".format(msgId))
            return
        receivedMsgs1[msgId] = True
        create_time = msg['CreateTime']  # 消息时间戳
        if int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[WX]history message {} skipped".format(msgId))
            return
        my_msg = msg["ToUserName"] == msg["User"]["UserName"] and \
                 msg["ToUserName"] != msg["FromUserName"]
        if my_msg and not is_group:
            logger.debug("[WX]my message {} skipped".format(msgId))
            return
        return func(msg, is_group)
    return wrapper

# 下载文件的函数
def download_files(msg):
    # 发送的文件的文件名（图片给出的默认文件名）都存储在msg的FileName键
    # 附件下载方法存储在msg的Text键中
    msg['Text'](msg['FileName'])
    return '@%s@%s' % ({'Picture': 'img', 'Video': 'vid', 'Attachment': 'fil'}.get(msg['Type'], 'fil'), msg['FileName'])

def get_group_nickname(UserName):
    groups = itchat.get_chatrooms(update=True)

    for group in groups:
        if group['UserName'] == UserName:  # 替换为要发送到的好友的昵称
            return group['NickName']

    groups = itchat.get_chatrooms(update=True)

    for group in groups:
        if group['UserName'] == UserName:  # 替换为要发送到的好友的昵称
            return group['NickName']

    return ''

def get_group_username(NickName):
    groups = itchat.get_chatrooms(update=True)

    for group in groups:
        if group['NickName'] == NickName:  # 替换为要发送到的好友的昵称
            return group['UserName']

    groups = itchat.get_chatrooms(update=True)

    for group in groups:
        if group['NickName'] == NickName:  # 替换为要发送到的好友的昵称
            return group['UserName']
    return ''

def get_signal_nickname(UserName):
    groups = itchat.get_friends(update=True)

    for group in groups:
        if group['UserName'] == UserName:  # 替换为要发送到的好友的昵称
            return group['NickName']

    groups = itchat.get_friends(update=True)

    for group in groups:
        if group['UserName'] == UserName:  # 替换为要发送到的好友的昵称
            return group['NickName']

    return ''

def get_signal_username(NickName):
    groups = itchat.get_friends(update=True)

    for group in groups:
        if group['NickName'] == NickName:  # 替换为要发送到的好友的昵称
            return group['UserName']

    groups = itchat.get_friends(update=True)

    for group in groups:
        if group['NickName'] == NickName:  # 替换为要发送到的好友的昵称
            return group['UserName']
    return ''


# 消息撤回处理
# @_msg_check
def just_revoke(msg, is_group=False):
    # a = itchat.get_contact(update=True)
    if not is_group:
        if msg['Type'] == 'Text' and msg['Text'].startswith('绑定'):
            bind_text = msg['Text']
            bind_text_list = bind_text.split('--')
            if len(bind_text_list) != 4:
                if is_group:
                    itchat.send_msg(
                        msg=f'绑定失败，绑定信息格式错误',
                        toUserName=msg['ToUserName'])
                else:
                    itchat.send_msg(
                        msg=f'绑定失败，绑定信息格式错误',
                        toUserName=msg['FromUserName'])
                return
            else:
                techgroup = bind_text_list[1]
                tech = bind_text_list[2]
                client = bind_text_list[3]
                # supervise = bind_text_list[3]

                # 创建新的Techclienttable对象并添加到数据库中
                new_tctable = Techclienttable(techgroup=techgroup, techname=tech, clientname=client)
                session.add(new_tctable)
                session.commit()

                itchat.send_msg(
                    msg=f'绑定成功',
                    toUserName=msg['FromUserName'])
                return

        elif msg['Type'] == 'Text' and msg['Text'].startswith('删除'):
            bind_text = msg['Text']
            bind_text_list = bind_text.split('--')
            if len(bind_text_list) != 4:
                if is_group:
                    itchat.send_msg(
                        msg=f'删除失败，绑定信息格式错误',
                        toUserName=msg['ToUserName'])
                else:
                    itchat.send_msg(
                        msg=f'删除失败，绑定信息格式错误',
                        toUserName=msg['FromUserName'])
                return
            else:
                techgroup = bind_text_list[1]
                tech = bind_text_list[2]
                client = bind_text_list[3]
                # supervise = bind_text_list[3]

                # 创建新的Techclienttable对象并添加到数据库中
                table = session.query(Techclienttable).filter_by(techgroup=techgroup, techname=tech, clientname=client)
                table.delete()
                session.commit()

                itchat.send_msg(
                    msg=f'删除成功',
                    toUserName=msg['FromUserName'])
                return

        if msg['FromUserName'] != msg['User']['UserName']:
            return

        # 就是发送消息的人的真实昵称
        ActualNickName = msg['User']['NickName']
        ActualUserName = msg['User']['UserName']

        # 判断表中是否已经存在该账号
        dicttable = session.query(DictTable).filter_by(Nickname= ActualNickName).first()
        if dicttable:
            if dicttable.Username != ActualUserName:
                dicttable.Username = ActualUserName
                session.commit()
        else:
            # 保存到表中
            dicttable = DictTable(Nickname= ActualNickName, Username= ActualUserName)
            session.add(dicttable)
            session.commit()
        # # 就是群昵称
        # NickName = msg['User']['NickName']

        # 查询是否有该技术绑定信息
        tctable = session.query(Techclienttable).filter_by(clientname=ActualNickName).first()

        if tctable:
            # 获取客户群昵称
            supervisename = tctable.techgroup
            clientNickname = tctable.clientname
            to_Nickname = clientNickname

            # 判断要发送的账号是否在数据库中
            dicttable = session.query(DictTable).filter_by(Nickname=supervisename).first()
            if dicttable:
                to_group_username = dicttable.Username
            else:
                to_group_username = get_group_username(supervisename)

            # to_Username = get_signal_username(clientNickname)


            # # 如果机器人不在群聊中
            # if to_group_username == '':
            #     itchat.send_msg(
            #         msg=f'警告：本账号不在绑定群聊中，请联系客服处理',
            #         toUserName=msg['User']['UserName'])
        else:
            # 查询是否有该客户绑定信息
            tctable = session.query(Techclienttable).filter_by(clientname=ActualNickName).first()
            if tctable:
                # 获取客户群昵称
                # supervisename = tctable.supervisegroup
                # techUsername = tctable.techname
                # to_Nickname = techUsername
                # to_Username = get_signal_username(techUsername)
                # to_group_username = get_group_username(supervisename)

                techgroupNickname = tctable.techgroup
                techNickname = tctable.clientname
                to_Nickname = techNickname
                to_Username = get_signal_username(techNickname)
                to_group_username = get_group_username(techgroupNickname)

                # # 如果机器人不在群聊中
                # if to_group_username == '':
                #     itchat.send_msg(
                #         msg=f'警告：本账号不在绑定群聊中，请联系客服处理',
                #         toUserName=msg['User']['UserName'])
            else:
                return
        # 原消息是文本消息
        if msg['Type'] == 'Text':
            old_msg_text = msg['Text']
            if '万重山' in old_msg_text:
                old_msg_text = old_msg_text.replace('万重山', to_Nickname)
            # itchat.send(msg=old_msg_text, toUserName=to_Username)
            itchat.send(msg=old_msg_text, toUserName=to_group_username)
        # 原消息是需要下载的文件消息
        elif msg['Type'] in ['Picture', 'Video', 'Attachment', 'Recording']:
            # # 判断文件大小是否大于10M
            # if msg['Type'] == 'Attachment' and float(msg['FileSize']) >= 10485760:
            #     itchat.send_msg(
            #         msg=f'提示：您发送文件过大，为了保证转发程序的正常运行，不对您的文件进行转发，请联系客服进行处理',
            #         toUserName=msg['User']['UserName'])
            #     return
            # 使用 download_files 函数下载文件
            file_info = download_files(msg).split('@')[-1]
            if msg['Type'] == 'Picture':
                # itchat.send_image(file_info, toUserName=to_Username)
                itchat.send_image(file_info, toUserName=to_group_username)
            elif msg['Type'] == 'Video':
                # itchat.send_video(file_info, toUserName=to_Username)
                itchat.send_video(file_info, toUserName=to_group_username)
            elif msg['Type'] == 'Recording':
                # pass
                # itchat.send_file(file_info, toUserName=to_Username)
                itchat.send_file(file_info, toUserName=to_group_username)
            else:
                # itchat.send_file(file_info, toUserName=to_Username)
                itchat.send_file(file_info, toUserName=to_group_username)
            os.remove(file_info)
    else:
        # 就是发送消息的人的真实昵称
        ActualNickName = msg['ActualNickName']
        # 就是群昵称
        NickName = msg['User']['NickName']

        # 就是个人的转发编号
        ActualUserName = msg['ActualUserName']
        # 就是群的转发编号
        UserName = msg['User']['UserName']

        # 判断表中是否已经存在该个人账号
        dicttable = session.query(DictTable).filter_by(Nickname=ActualNickName).first()
        if dicttable:
            if dicttable.Username != ActualUserName:
                dicttable.Username = ActualUserName
                session.commit()
        else:
            # 保存到表中
            dicttable = DictTable(Nickname=ActualNickName, Username=ActualUserName)
            session.add(dicttable)
            session.commit()

        # 判断表中是否已经存在该群账号
        dicttable = session.query(DictTable).filter_by(Nickname=NickName).first()
        if dicttable:
            if dicttable.Username != UserName:
                dicttable.Username = UserName
                session.commit()
        else:
            # 保存到表中
            dicttable = DictTable(Nickname=NickName, Username=UserName)
            session.add(dicttable)
            session.commit()


        # 查询是否有该技术绑定信息
        tctable = session.query(Techclienttable).filter_by(techgroup = NickName, techname=ActualNickName).first()

        if tctable:
            # 获取客户群昵称
            # techgroupNickname = tctable.techgroup
            clientNickname = tctable.clientname
            to_Nickname = clientNickname

            # 判断要发送的账号是否在数据库中
            dicttable = session.query(DictTable).filter_by(Nickname=to_Nickname).first()
            if dicttable:
                to_Username = dicttable.Username
            else:
                to_Username = get_signal_username(clientNickname)
            # to_group_username = get_group_username(techgroupNickname)

            # # 如果机器人不在群聊中
            # if to_group_username == '':
            #     itchat.send_msg(
            #         msg=f'警告：本账号不在绑定群聊中，请联系客服处理',
            #         toUserName=msg['User']['UserName'])
        else:
            return
        # 原消息是文本消息
        if msg['Type'] == 'Text':
            old_msg_text = msg['Text']
            if '万重山' in old_msg_text:
                old_msg_text = old_msg_text.replace('万重山', to_Nickname)
            itchat.send(msg=old_msg_text, toUserName=to_Username)
            # itchat.send(msg=old_msg_text, toUserName= to_group_username)
        # 原消息是需要下载的文件消息
        elif msg['Type'] in ['Picture', 'Video', 'Attachment', 'Recording']:
            # # 判断文件大小是否大于10M
            # if msg['Type'] == 'Attachment' and float(msg['FileSize']) >= 10485760:
            #     itchat.send_msg(
            #         msg=f'提示：您发送文件过大，为了保证转发程序的正常运行，不对您的文件进行转发，请联系客服进行处理',
            #         toUserName=msg['User']['UserName'])
            #     return
            # 使用 download_files 函数下载文件
            file_info = download_files(msg).split('@')[-1]
            if msg['Type'] == 'Picture':
                itchat.send_image(file_info, toUserName=to_Username)
                # itchat.send_image(file_info, toUserName=to_group_username)
            elif msg['Type'] == 'Video':
                itchat.send_video(file_info, toUserName=to_Username)
                # itchat.send_video(file_info, toUserName=to_group_username)
            elif msg['Type'] == 'Recording':
                # pass
                itchat.send_file(file_info, toUserName=to_Username)
                # itchat.send_file(file_info, toUserName=to_group_username)
            else:
                itchat.send_file(file_info, toUserName=to_Username)
                # itchat.send_file(file_info, toUserName=to_group_username)
            os.remove(file_info)


    # try:
    #     if msg["Type"] == 'Text':
    #         msg_dict[msg['MsgId']] = msg
    #     elif msg["Type"] in ['Picture', 'Video', 'Attachment', 'Recording']:
    #         # 存到字典
    #         msg_dict[msg['MsgId']] = msg
    #         # 使用 download_files 函数下载文件
    #         file_info = download_files(msg)
    #         msg_dict[msg['MsgId']]['FileName'] = file_info.split('@')[-1]
    #     elif msg["Type"] == 'Note':
    #         revoke_msg(msg, is_group)
    # except Exception as e:
    #     logger.exception('防撤回异常：消息类型：{}'.format(msg["Type"]), e)

@itchat.msg_register([TEXT, VOICE, PICTURE, NOTE, ATTACHMENT, SHARING, VIDEO])
def handler_single_msg(msg):
    try:
        print(f'测试{msg}')
        just_revoke(msg, False)
        # cmsg = WechatMessage(msg, False)
    except NotImplementedError as e:
        logger.debug("[WX]single message {} skipped: {}".format(msg["MsgId"], e))
        return None
    # WechatChannel().handle_single(cmsg)
    return None


@itchat.msg_register([TEXT, VOICE, PICTURE, NOTE, ATTACHMENT, SHARING, VIDEO], isGroupChat=True)
def handler_group_msg(msg):
    try:
        print(f'测试{msg}')
        just_revoke(msg, True)
        # cmsg = WechatMessage(msg, True)
    except NotImplementedError as e:
        logger.debug("[WX]group message {} skipped: {}".format(msg["MsgId"], e))
        return None
    # WechatChannel().handle_group(cmsg)
    return None


# 后面的毫无改动


def _check(func):
    def wrapper(self, cmsg: ChatMessage):
        msgId = cmsg.msg_id
        if msgId in self.receivedMsgs:
            logger.info("Wechat message {} already received, ignore".format(msgId))
            return
        self.receivedMsgs[msgId] = True
        create_time = cmsg.create_time  # 消息时间戳
        if conf().get("hot_reload") == True and int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[WX]history message {} skipped".format(msgId))
            return
        if cmsg.my_msg and not cmsg.is_group:
            logger.debug("[WX]my message {} skipped".format(msgId))
            return
        return func(self, cmsg)

    return wrapper


# 可用的二维码生成接口
# https://api.qrserver.com/v1/create-qr-code/?size=400×400&data=https://www.abc.com
# https://api.isoyu.com/qr/?m=1&e=L&p=20&url=https://www.abc.com
def qrCallback(uuid, status, qrcode):
    # logger.debug("qrCallback: {} {}".format(uuid,status))
    if status == "0":
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(qrcode))
            _thread = threading.Thread(target=img.show, args=("QRCode",))
            _thread.setDaemon(True)
            _thread.start()
        except Exception as e:
            pass

        import qrcode

        url = f"https://login.weixin.qq.com/l/{uuid}"

        qr_api1 = "https://api.isoyu.com/qr/?m=1&e=L&p=20&url={}".format(url)
        qr_api2 = "https://api.qrserver.com/v1/create-qr-code/?size=400×400&data={}".format(url)
        qr_api3 = "https://api.pwmqr.com/qrcode/create/?url={}".format(url)
        qr_api4 = "https://my.tv.sohu.com/user/a/wvideo/getQRCode.do?text={}".format(url)
        print("You can also scan QRCode in any website below:")
        print(qr_api3)
        print(qr_api4)
        print(qr_api2)
        print(qr_api1)
        _send_qr_code([qr_api3, qr_api4, qr_api2, qr_api1])
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)


@singleton
class WechatChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = []

    def __init__(self):
        super().__init__()
        self.receivedMsgs = ExpiredDict(conf().get("expires_in_seconds"))
        self.auto_login_times = 0

    def startup(self):
        try:
            itchat.instance.receivingRetryCount = 600  # 修改断线超时时间
            # login by scan QRCode
            hotReload = conf().get("hot_reload", False)
            status_path = os.path.join(get_appdata_dir(), "itchat.pkl")
            itchat.auto_login(
                enableCmdQR=2,
                hotReload=hotReload,
                statusStorageDir=status_path,
                qrCallback=qrCallback,
                exitCallback=self.exitCallback,
                loginCallback=self.loginCallback
            )
            self.user_id = itchat.instance.storageClass.userName
            self.name = itchat.instance.storageClass.nickName
            logger.info("Wechat login success, user_id: {}, nickname: {}".format(self.user_id, self.name))
            # start message listener
            itchat.run()
        except Exception as e:
            logger.exception(e)

    def exitCallback(self):
        try:
            from common.linkai_client import chat_client
            if chat_client.client_id and conf().get("use_linkai"):
                _send_logout()
                time.sleep(2)
                self.auto_login_times += 1
                if self.auto_login_times < 100:
                    chat_channel.handler_pool._shutdown = False
                    self.startup()
        except Exception as e:
            pass

    def loginCallback(self):
        logger.debug("Login success")
        _send_login_success()

    # handle_* 系列函数处理收到的消息后构造Context，然后传入produce函数中处理Context和发送回复
    # Context包含了消息的所有信息，包括以下属性
    #   type 消息类型, 包括TEXT、VOICE、IMAGE_CREATE
    #   content 消息内容，如果是TEXT类型，content就是文本内容，如果是VOICE类型，content就是语音文件名，如果是IMAGE_CREATE类型，content就是图片生成命令
    #   kwargs 附加参数字典，包含以下的key：
    #        session_id: 会话id
    #        isgroup: 是否是群聊
    #        receiver: 需要回复的对象
    #        msg: ChatMessage消息对象
    #        origin_ctype: 原始消息类型，语音转文字后，私聊时如果匹配前缀失败，会根据初始消息是否是语音来放宽触发规则
    #        desire_rtype: 希望回复类型，默认是文本回复，设置为ReplyType.VOICE是语音回复
    @time_checker
    @_check
    def handle_single(self, cmsg: ChatMessage):
        # filter system message
        if cmsg.other_user_id in ["weixin"]:
            return
        if cmsg.ctype == ContextType.VOICE:
            if conf().get("speech_recognition") != True:
                return
            logger.debug("[WX]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[WX]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[WX]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[WX]receive text msg: {}, cmsg={}".format(json.dumps(cmsg._rawmsg, ensure_ascii=False), cmsg))
        else:
            logger.debug("[WX]receive msg: {}, cmsg={}".format(cmsg.content, cmsg))
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg)
        if context:
            self.produce(context)

    @time_checker
    @_check
    def handle_group(self, cmsg: ChatMessage):
        if cmsg.ctype == ContextType.VOICE:
            if conf().get("group_speech_recognition") != True:
                return
            logger.debug("[WX]receive voice for group msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[WX]receive image for group msg: {}".format(cmsg.content))
        elif cmsg.ctype in [ContextType.JOIN_GROUP, ContextType.PATPAT, ContextType.ACCEPT_FRIEND, ContextType.EXIT_GROUP]:
            logger.debug("[WX]receive note msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            # logger.debug("[WX]receive group msg: {}, cmsg={}".format(json.dumps(cmsg._rawmsg, ensure_ascii=False), cmsg))
            pass
        elif cmsg.ctype == ContextType.FILE:
            logger.debug(f"[WX]receive attachment msg, file_name={cmsg.content}")
        else:
            logger.debug("[WX]receive group msg: {}".format(cmsg.content))
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
        if context:
            self.produce(context)

    # 统一的发送函数，每个Channel自行实现，根据reply的type字段发送不同类型的消息
    def send(self, reply: Reply, context: Context):
        receiver = context["receiver"]
        print(f'测试回复：{context}')
        if reply.type == ReplyType.TEXT:
            itchat.send(reply.content, toUserName=receiver)
            logger.info("[WX] sendMsg={}, receiver={}".format(reply, receiver))
        elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
            itchat.send(reply.content, toUserName=receiver)
            logger.info("[WX] sendMsg={}, receiver={}".format(reply, receiver))
        elif reply.type == ReplyType.VOICE:
            itchat.send_file(reply.content, toUserName=receiver)
            logger.info("[WX] sendFile={}, receiver={}".format(reply.content, receiver))
        elif reply.type == ReplyType.IMAGE_URL:  # 从网络下载图片
            img_url = reply.content
            logger.debug(f"[WX] start download image, img_url={img_url}")
            pic_res = requests.get(img_url, stream=True)
            image_storage = io.BytesIO()
            size = 0
            for block in pic_res.iter_content(1024):
                size += len(block)
                image_storage.write(block)
            logger.info(f"[WX] download image success, size={size}, img_url={img_url}")
            image_storage.seek(0)
            itchat.send_image(image_storage, toUserName=receiver)
            logger.info("[WX] sendImage url={}, receiver={}".format(img_url, receiver))
        elif reply.type == ReplyType.IMAGE:  # 从文件读取图片
            image_storage = reply.content
            image_storage.seek(0)
            itchat.send_image(image_storage, toUserName=receiver)
            logger.info("[WX] sendImage, receiver={}".format(receiver))
        elif reply.type == ReplyType.FILE:  # 新增文件回复类型
            file_storage = reply.content
            itchat.send_file(file_storage, toUserName=receiver)
            logger.info("[WX] sendFile, receiver={}".format(receiver))
        elif reply.type == ReplyType.VIDEO:  # 新增视频回复类型
            video_storage = reply.content
            itchat.send_video(video_storage, toUserName=receiver)
            logger.info("[WX] sendFile, receiver={}".format(receiver))
        elif reply.type == ReplyType.VIDEO_URL:  # 新增视频URL回复类型
            video_url = reply.content
            logger.debug(f"[WX] start download video, video_url={video_url}")
            video_res = requests.get(video_url, stream=True)
            video_storage = io.BytesIO()
            size = 0
            for block in video_res.iter_content(1024):
                size += len(block)
                video_storage.write(block)
            logger.info(f"[WX] download video success, size={size}, video_url={video_url}")
            video_storage.seek(0)
            itchat.send_video(video_storage, toUserName=receiver)
            logger.info("[WX] sendVideo url={}, receiver={}".format(video_url, receiver))

def _send_login_success():
    try:
        from common.linkai_client import chat_client
        if chat_client.client_id:
            chat_client.send_login_success()
    except Exception as e:
        pass

def _send_logout():
    try:
        from common.linkai_client import chat_client
        if chat_client.client_id:
            chat_client.send_logout()
    except Exception as e:
        pass

def _send_qr_code(qrcode_list: list):
    try:
        from common.linkai_client import chat_client
        if chat_client.client_id:
            chat_client.send_qrcode(qrcode_list)
    except Exception as e:
        pass
