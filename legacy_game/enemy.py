import pygame
import random

from bullet import EnemyBullet

class EnemyPlane(object):
    def __init__(self,screen):
        self.direction="right"
        self.screen = screen  # 定义窗口
        self.x = random.randint(0,394)
        self.y = random.randint(0,150)
        self.imageid = "enemy0.png"  # 飞机图像路径
        self.image = pygame.image.load(self.imageid)  # 载入飞机图像
        self.image = pygame.transform.scale(self.image,(30,30))
        self.rect = self.image.get_rect()
        self.rect.x = self.x
        self.rect.y = self.y
        self.bulletlist=[]
        self.alive=True#敌机存活
        self.dead_time=0#敌机死亡时间
    def display(self):
        if self.alive:
            self.screen.blit(self.image,(self.x,self.y))
        needDelItemList = []  # 创建一个列表，把要删除的子弹存放到里面
        for item in self.bulletlist:
            if item.judge():  # 调用子弹类里面的judge方法
                needDelItemList.append(item)  # return Ture和return False决定是否把子弹元素放进needDelItemList里面进行删除
            pass
        # 重新遍历一下
        for i in needDelItemList:
            self.bulletlist.remove(i)  # 利用needDelItemList里面的子弹元素对self.bulletlist子弹列表进行删除
            pass
        for bullet in self.bulletlist:
            bullet.display()  # 调用子弹类里面的display()显示未被删除的子弹
            bullet.move()  # 调用子弹类里面的move()方法，让子弹进行移动
        pass
    def move(self):
        if self.direction == "right":
            self.x+=1
            pass
        elif self.direction == "left":
            self.x-=1
            pass
        self.rect.x=self.x
        if self.x>404:
            self.direction="left"
            pass
        elif self.x<0:
            self.direction="right"
    def enemyfire(self):
        num=random.randint(1,180)
        if num==3:
            newbullet=EnemyBullet(self.rect.centerx,self.rect.bottom,self.screen)#这里给敌机子弹传递了飞机坐标的参数
            self.bulletlist.append(newbullet)
        pass
