import { Component, OnInit, inject, signal } from '@angular/core';
import { AuthService } from './auth.service';

@Component({
  selector: 'app-root',
  imports: [],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  protected readonly title = signal('Honor Code');
  protected readonly auth = inject(AuthService);

  ngOnInit(): void {
    this.auth.refresh();
  }

  protected login(): void {
    this.auth.login();
  }
}
