import pygame
import sys
from pygame.locals import *

def key_control(HeroPlane, game_over):
    evenlist = pygame.event.get()
    for event in evenlist:
        if event.type == QUIT:
            print("退出游戏")
            sys.exit()
    if game_over:
        return

    keys = pygame.key.get_pressed()
    if keys[K_a] or keys[K_LEFT]:
        print("left")
        HeroPlane.moveleft()
    if keys[K_d] or keys[K_RIGHT]:
        print("right")
        HeroPlane.moveright()
    if keys[K_SPACE]:
        HeroPlane.fire()