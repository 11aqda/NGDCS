def check_bullet_enemy(hero,enemy):
    for bullet in hero.bulletlist:
        if bullet.rect.colliderect(enemy.rect):#检测如果bullet和敌机重叠
            return bullet
    return None

def check_enemybullet_hero(hero,enemy):
    for bullet in enemy.bulletlist:
        if bullet.rect.colliderect(hero.rect):
            return bullet
    return None