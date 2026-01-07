import pygame
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_asset_path(*relative):
    return os.path.join(BASE_DIR, "assets", *relative)

def show_splash(screen, clock):
    # Khởi tạo âm thanh nếu main chưa khởi tạo
    if not pygame.mixer.get_init():
        pygame.mixer.init()

    # 1. Tải và xử lý hình ảnh
    img_path = os.path.join(BASE_DIR, "sp.png")
    if not os.path.exists(img_path):
        img_path = get_asset_path("sp.png")

    try:
        splash_img = pygame.image.load(img_path).convert_alpha()
        
        # --- CHỈNH LẠI KÍCH THƯỚC Ở ĐÂY ---
        screen_w, screen_h = screen.get_size()
        
        # Để ảnh to hơn, chúng ta cho nó bằng 85% chiều cao màn hình (khoảng 510px)
        target_h = int(screen_h * 0.85) 
        target_w = target_h # Vì ảnh của bạn là hình vuông 1024x1024
        
        # Dùng smoothscale để ảnh không bị vỡ hạt khi thu nhỏ
        splash_img = pygame.transform.smoothscale(splash_img, (target_w, target_h))
        # ---------------------------------
        
    except Exception as e:
        print(f"Lỗi: {e}")
        return 

    img_rect = splash_img.get_rect(center=(screen_w // 2, screen_h // 2))
    
    # 2. Tải âm thanh (giữ nguyên)
    try:
        pygame.mixer.music.load(get_asset_path("music", "whosh.mp3"))
        pygame.mixer.music.set_volume(0.6)
        pygame.mixer.music.play()
    except:
        pass

    alpha = 0
    fade_speed = 5
    state = "FADE_IN"
    wait_time = 100 
    
    running = True
    while running:
        screen.fill((0, 0, 0)) 
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN or event.type == pygame.MOUSEBUTTONDOWN:
                running = False

        if state == "FADE_IN":
            alpha += fade_speed
            if alpha >= 255:
                alpha = 255
                state = "WAIT"
        elif state == "WAIT":
            wait_time -= 1
            if wait_time <= 0:
                state = "FADE_OUT"
        elif state == "FADE_OUT":
            alpha -= fade_speed
            if alpha <= 0:
                running = False

        # Vẽ ảnh
        splash_img.set_alpha(alpha)
        screen.blit(splash_img, img_rect)
        
        pygame.display.update()
        clock.tick(60)
