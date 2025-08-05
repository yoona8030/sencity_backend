from django.shortcuts import render
from .models import CCTVDevice, MotionSensor

def dashboard_home(request):
    # 더미 데이터
    devices = [
        type('D', (), {'name':'CCTV 1','status':'ONLINE'})(),
        type('D', (), {'name':'CCTV 2','status':'OFFLINE'})(),
        type('D', (), {'name':'CCTV 3','status':'OFFLINE'})(),
        type('D', (), {'name':'CCTV 4','status':'OFFLINE'})(),
    ]
    sensors = [
        type('S', (), {'device':devices[0],'status':'감지됨'})(),
        type('S', (), {'device':devices[1],'status':'오프라인'})(),
        type('S', (), {'device':devices[2],'status':'오프라인'})(),
        type('S', (), {'device':devices[3],'status':'오프라인'})(),
    ]

    # 디버깅용 로그
    print("DEVICES:", devices)
    print("SENSORS:", sensors)

    # 테스트용 로컬 동영상 링크
    video_url = '/static/dashboard/videos/sample.mp4'

    # 중괄호는 dict만, 함수 닫을 때는 ')' 하나만!
    return render(request, 'dashboard/home.html', {
        'devices': devices,
        'sensors': sensors,
        'video_url': video_url,
    })
