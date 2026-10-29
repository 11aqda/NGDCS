import pygame

class Bullet(object):
    def __init__(self,x,y,screen):
        self.x=x+13#控制子弹在飞机的中间
        self.y=y-18#控制子弹在飞机的机头
        self.screen=screen#载入窗口a
        self.image=pygame.image.load("bullet.png")#载入子弹图片
        self.rect=self.image.get_rect()
        self.rect.x=self.x
        self.rect.y=self.y
        pass
    def display(self):
        self.screen.blit(self.image,(self.x,self.y))#将子弹放入窗口
        pass
    def move(self):
        self.y-=2.5#利用递减大小来控制子弹飞行速度
        self.rect.y=self.y
        pass
    #判断子弹是否越界et
    def judge(self):
        if self.y<0:
            return True
        else:
            return False

class EnemyBullet(object):
    def __init__(self,x,y,screen):
        self.x=x#控制子弹在飞机的中间
        self.y=y#控制子弹在飞机的机头
        self.screen=screen#载入窗口a
        self.image=pygame.image.load("bullet.png")#载入子弹图片
        self.rect=self.image.get_rect()
        self.rect.x=self.x
        self.rect.y=self.y
        pass
    def display(self):
        self.screen.blit(self.image,(self.x,self.y))#将子弹放入窗口
        pass
    def move(self):
        self.y+=3#利用递减大小来控制子弹飞行速度
        self.rect.y=self.y
        pass
    #判断子弹是否越界
    def judge(self):
        if self.y>600:
            return True
        else:
            return False