import random
import sys
import pygame
from pygame.locals import *

from bullet import Bullet,EnemyBullet
from player import HeroPlane
from enemy import EnemyPlane
from control import key_control
from collision import check_bullet_enemy,check_enemybullet_hero


def main():
    pygame.init()
    #创建一个窗口，用来显示内容
    screen=pygame.display.set_mode((424,600))#图片比例
    #创建一个背景图像
    background=pygame.image.load("1a48eaddc6dbe8c80b3c0ac45fac0592.jpg")
    #设置一个title
    pygame.display.set_caption("飞机小游戏")
    #添加背景音乐
    pygame.mixer.init()#初始化
    pygame.mixer.music.load("冒险岛游戏 - 天空之城.mp3")
    pygame.mixer.music.set_volume(0.2)#音量（0-1）
    pygame.mixer.music.play(-1)#-1表示无限循环音乐
    #创建一个飞机对象
    hero=HeroPlane(screen)
    #创建一个敌机对象
    enemylist=[]
    for i in range(3):
        enemylist.append(EnemyPlane(screen))
    score=0#初始击杀分数
    game_over=False#游戏正在进行
    font=pygame.font.SysFont(None,40)#字体模块，None默认字体。40像素大小
    clock=pygame.time.Clock()
    #设定要显示的内容
    while True:
        for event in pygame.event.get():#跳出游戏结束，防止不能x退游戏
            if event.type==QUIT:
                pygame.quit()
                sys.exit()

        screen.blit(background, (0, 0))  # 把背景放到窗口上（screen）,()里面的是坐标坐标

        if not game_over:
            for enemyplane in enemylist:#多敌机
                if enemyplane.alive:
                    enemyplane.enemyfire()
                    enemyplane.move()
                    enemyplane.display()
                if not  enemyplane.alive:
                    if pygame.time.get_ticks() - enemyplane.dead_time>3000:
                        enemyplane.x=random.randint(0,394)
                        enemyplane.y=random.randint(0,150)
                        enemyplane.rect.x=enemyplane.x
                        enemyplane.rect.y=enemyplane.y
                        enemyplane.bulletlist=[]
                        enemyplane.alive=True
            hero.display()
            for enemyplane in enemylist:
                if enemyplane.alive:
                    hit_bullet = check_bullet_enemy(hero,enemyplane)
                    if hit_bullet:
                        print("击中了敌机")
                        hero.bulletlist.remove(hit_bullet)
                        enemyplane.alive=False
                        enemyplane.dead_time=pygame.time.get_ticks()
                        score+=10#击杀后加分
                    hit_enemy_bullet=check_enemybullet_hero(hero,enemyplane)
                    if hit_enemy_bullet:
                        print("玩家被击中了")
                        enemyplane.bulletlist.remove(hit_enemy_bullet)
                        hero.hp-=1

                    if hero.hp<=0:
                        print("游戏结束")
                        game_over=True
            key_control(hero,game_over)#必须要传递实例hero，不能传递类HeroPlane
        score_text = font.render("Score:" + str(score), True, (255, 255, 0))  # 生成文字图片
        screen.blit(score_text, (10, 10))
        hp_text = font.render("HP:" + str(hero.hp), True, (255, 255, 0))
        screen.blit(hp_text, (10, 50))
        if game_over:
            game_over_text = font.render("Game over!", True, (255, 255, 0))
            screen.blit(game_over_text, (140, 280))
            final_score_text = font.render("Score:" + str(score), True, (255, 255, 0))  # 最终分数
            screen.blit(final_score_text, (140, 330))

        pygame.display.update()
        clock.tick(60)#控制循环频率
        #背景→飞机→更新屏幕。如果顺序颠倒，飞机会被背景覆盖。
if __name__ == '__main__':
    main()