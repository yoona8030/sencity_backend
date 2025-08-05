from django.contrib import admin
from .models import User, SearchHistory, Animal

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'telphone', 'address', 'agree')
    search_fields = ('username', 'email', 'telphone')
    
@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display = ('name_kor', 'name_eng')
    search_fields = ('name_kor', 'name_eng')

@admin.register(SearchHistory)
class SearchHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'keyword', 'searched_at')
    search_fields = ('keyword',)
    list_filter = ('user',)