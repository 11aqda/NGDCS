import pygame
from bullet import Bullet

class HeroPlane(object):
    def __init__(self,screen):#初始化
        self.screen=screen#定义窗口
        self.x=190
        self.y=480
        self.imageid="hero.png"#飞机图像路径
        self.image=pygame.image.load(self.imageid)#载入飞机图像
        self.rect=self.image.get_rect()#给飞机图片弄一个矩形面积，用于碰撞测试
        self.rect.x = self.x
        self.rect.y = self.y
        self.bulletlist=[]#创建一个子弹列表，用于存放子弹
        self.last_shoot_time=0#子弹上一次发射时间
        self.shoot_delay=300#子弹发射时间间隔
        self.hp=3#玩家初始生命值
        pass
    def moveleft(self):
        if self.x>0:
            self.x-=8#利用控制x大小来控制飞机移动
            self.rect.x=self.x
        pass
    def moveright(self):
        if self.x<376:#图像宽度424-飞机宽度48
            self.x+=8#利用控制x大小来控制飞机移动
            self.rect.x=self.x
        pass
    def display(self):
        self.screen.blit(self.image,(self.x,self.y))##把飞机放到窗口上，（）里面是坐标
        needDelItemList=[]#创建一个列表，把要删除的子弹存放到里面
        for item in self.bulletlist:
            if item.judge():#调用子弹类里面的judge方法
                needDelItemList.append(item)#return Ture和return False决定是否把子弹元素放进needDelItemList里面进行删除
            pass
        #重新遍历一下
        for i in needDelItemList:
            self.bulletlist.remove(i)#利用needDelItemList里面的子弹元素对self.bulletlist子弹列表进行删除
            pass
        for bullet in self.bulletlist:
            bullet.display()#调用子弹类里面的display()显示未被删除的子弹
            bullet.move()#调用子弹类里面的move()方法，让子弹进行移动
    #发射子弹
    def fire(self):
        now=pygame.time.get_ticks()
        if now - self.last_shoot_time >= self.shoot_delay:
            newbullet=Bullet(self.x,self.y,self.screen)#这里给子弹类传入了参数
            self.bulletlist.append(newbullet)#把子弹存入bulletlist子弹列表
            self.last_shoot_time=now
